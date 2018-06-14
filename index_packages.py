#!/usr/bin/python3

# The MIT License (MIT)
# 
# Copyright (c) 2018 Yury Gribov
# 
# Use of this source code is governed by The MIT License (MIT)
# that can be found in the LICENSE.txt file.

import os
import os.path
import sys
import shutil
import gzip
import glob
import datetime
import subprocess
import argparse

import queue

from elftools.elf.elffile import ELFFile
from elftools.elf.sections import SymbolTableSection
from elftools.elf.dynamic import DynamicSection, DynamicSegment
from elftools.elf.relocation import RelocationSection
from elftools.elf.descriptions import describe_reloc_type
from elftools.elf.gnuversions import GNUVerDefSection

import magic
import MySQLdb

from lib.errors import (error, warn, enable_raise_on_error, set_prog_name, Error)
from lib import database
from lib.model import (Package, Object, Symbol, create_schema)
from lib import parallel_map
from lib import linker
from lib.analysis import mean

def get_packages(lst):
  pkgs = []
  with open(lst, 'r') as f:
    for l in f.readlines():
      l = l.strip()
      if l.startswith('#'):
        continue
      parts = l.split(' ')
      name = parts[0]
      version = parts[1] if len(parts) > 1 else None
      component = parts[2] if len(parts) > 2 else None
      pkgs.append(Package(name))
  return pkgs

def parse_elf_file(f, file_type, pkg):
  is_shlib = 'shared object' in file_type \
    and '.so' in file_type  # Detect PIEs

  with open(f, 'rb') as stream:
    elf_file = ELFFile(stream)
    f = os.path.basename(f)

    # First collect dependency info
    dynsect = elf_file.get_section_by_name('.dynamic')
    if not dynsect:
      error("%s: no .dynamic section" % f)
    elif not isinstance(dynsect, DynamicSection):
      # TODO: investigate
      error("%s: unexpected type of .dynamic" % f)
    soname = None
    deps = []
    is_symbolic = False
    for tag in dynsect.iter_tags():
      if tag.entry.d_tag == 'DT_NEEDED':
        deps.append(tag.needed)
      elif tag.entry.d_tag == 'DT_SONAME':
        if soname is not None:
          error("%s: multiple DT_SONAME in .dynamic section" % f)
        soname = tag.soname
      elif tag.entry.d_tag == 'DT_SYMBOLIC' \
          or (tag.entry.d_tag == 'DT_FLAGS' and (tag.entry.d_val & 0x2)):
        is_symbolic = True
    if not deps and not linker.is_dynamic_linker(f):
      warn("%s: no DT_NEEDED in .dynamic section" % f)

    # Get copy relocs (they are not real exports)
    copy_relocated_addresses = set()
    reladyn_name = '.rela.dyn'
    reladyn = elf_file.get_section_by_name(reladyn_name)
    if not isinstance(reladyn, RelocationSection):
        warn("%s: unexpected type of .rela.dyn" % f)
    else:
      # The symbol table section pointed to in sh_link
      for rel in reladyn.iter_relocations():
        rel_type = describe_reloc_type(rel['r_info_type'], elf_file)
        if rel_type == 'R_X86_64_COPY':
          copy_relocated_addresses.add(rel['r_offset'])

    # Get version names
    verdef = elf_file.get_section_by_name('.gnu.version_d')
    ver_names = set()
    if verdef:
      if not isinstance(verdef, GNUVerDefSection):
        error("%s: unexpected type of .gnu.version_d" % f)
      else:
        for verdef, verdaux_iter in verdef.iter_versions():
          verdaux = next(verdaux_iter)
          ver_names.add(verdaux.name)

    # Now analyze interface
    # TODO: versions
    symtab = elf_file.get_section_by_name('.dynsym')
    if not symtab:
      error("%s: no symbol table in %s")
      return False
    elif not isinstance(symtab, SymbolTableSection):
      error("%s: unexpected type of .dynsym" % f)
      return False

    obj = Object(f, soname, pkg, deps, [], [], is_shlib, is_symbolic)

    for ndx, elf_symbol in enumerate(symtab.iter_symbols()):
      bind = elf_symbol['st_info']['bind']
      vis = elf_symbol['st_other']['visibility']
      # STB_LOOS means STB_GNU_UNIQUE
      if bind in ('STB_GLOBAL', 'STB_WEAK', 'STB_LOOS') \
          and vis in ('STV_DEFAULT', 'STV_PROTECTED'):
        if elf_symbol.name in ver_names:
          continue
        symbol = Symbol(elf_symbol.name, obj, bind == 'STB_WEAK', vis == 'STV_PROTECTED')
        if elf_symbol['st_shndx'] == 'SHN_UNDEF' \
            or elf_symbol['st_value'] in copy_relocated_addresses:
          obj.imports.append(symbol)
        else:
          obj.exports.append(symbol)

  return obj

def run(cmd, wd):
  p = subprocess.Popen(cmd.split(' '), stdin=None, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=wd)
  out, err = p.communicate()
  if p.returncode != 0:
    error("%s returned %d" % (cmd, p.returncode))
  return out.decode(), err.decode()

class Stats:
  def __init__(self, objects, total_time, db_time, num_inserts, has_errors):
    self.total_time = total_time
    self.db_time = db_time
    self.num_inserts = num_inserts
    self.nobjs = len(objects)
    self.ndeps = sum(len(obj.deps) for obj in objects)
    self.nsyms = sum((len(obj.imports) + len(obj.exports)) for obj in objects)
    self.has_errors = has_errors

  def __str__(self):
    return "time = %g, nobjs = %d, ndeps = %d, nsyms = %d" % (self.time, self.nobjs, self.ndeps, self.nsyms)

def collect_pkg_data(pkg, wd_root, conn, v):
  t0 = datetime.datetime.now()

  wd = os.path.join(wd_root, pkg.name)
  os.mkdir(wd)

  error_msg = None
  m = magic.Magic(uncompress=True)
  objects = []

  # Download and analyze package

  try:
    out, _  = run('apt-cache showsrc %s' % pkg.name, wd)
    source_name = None
    for line in out.split('\n'):
      if line.startswith('Package: '):
        source_name = line.split(' ')[1]
    if source_name is None:
      raise Error("source package not found")
    pkg.source_name = source_name

    run('apt-get -qq -d download %s' % pkg.name, wd)
    for deb in glob.glob(os.path.join(wd, '*.deb')):
      run('ar x %s' % os.path.basename(deb), wd)
      for ar in glob.glob(os.path.join(wd, 'data.tar*')):
        run('tar xf %s' % os.path.basename(ar), wd)

    for root, _, files in os.walk(wd):
      for basename in files:
        f = os.path.join(root, basename)
        if os.path.isfile(f) and not os.path.islink(f):
          file_type = m.from_file(f)
          if file_type.startswith('ELF '):
            objects.append(parse_elf_file(f, file_type, pkg))
  except Error as e:
    error_msg = e.message
    pkg.has_errors = True

  if v:
    print('ELFs in package %s' % pkg.name)
    for obj in objects:
      print(str(obj))

  # Store in db

  t1 = datetime.datetime.now()

  with conn as cur:
    pkg.serialize(cur, error_msg)

  total_inserts = 0
  for obj in objects:
    with conn as cur:
      obj.serialize(cur, pkg.id)
      total_inserts += len(obj.deps) + len(obj.imports) + len(obj.exports)

  t2 = datetime.datetime.now()

  return Stats(objects, (t2 - t0).total_seconds(), (t2 - t1).total_seconds(),
               total_inserts, error_msg is not None)

def main():
  parser = argparse.ArgumentParser(description="Analyze contents of Debian binary packages and store them to database.")
  parser.add_argument('pkglist', metavar='PKGLIST', help="File with package names.")
  parser.add_argument('--verbose', '-v', action='count', help="Print diagnostic info.", default=0)
  parser.add_argument('--db-name', help="Database name.", default='syms')
  parser.add_argument('-j', dest='num_threads', help="Number of threads.", type=int, default=None)
  parser.add_argument('-o', dest='output', help="Output folder.", default='tmp')
  parser.add_argument('--stats', dest='stats', help="Print statistics before exit.", action='store_true')
  parser.add_argument('--no-stats', dest='stats', help="Do not print statistics before exit.", action='store_false')
  parser.set_defaults(stats=True)

  args = parser.parse_args()

  wd = os.path.abspath(args.output)
  if os.path.isdir(wd):
    shutil.rmtree(wd)
  os.mkdir(wd)

  create_schema(args.db_name)

  pkgs = get_packages(args.pkglist)
  npkgs = len(pkgs)

  enable_raise_on_error()
  set_prog_name(os.path.basename(__file__))

  def do_work(pkg, ctx):
    if ctx[0] is None:
      ctx[0] = database.connect_for_bulk_inserts(args.db_name)
    conn = ctx[0]
    return collect_pkg_data(pkg, wd, conn, args.verbose)

  res_lists, exc_lists = parallel_map.map(do_work, pkgs, args.num_threads)

  if args.stats:
    print("Number of packages: %d" % npkgs)

    wall_time = max(sum(r.total_time for r in lst) for lst in res_lists)
    print("Wall time: %d:%d" % (wall_time / 60, wall_time % 60))

    results = [r for lst in res_lists for r in lst]
    times = [r.total_time for r in results]
    print("Average time to process a package: %g sec." % mean(times))

    rps = int(sum(map(lambda stat: stat.num_inserts, results)) / wall_time if wall_time else 0)
    print("RPS: %d" % rps)

    deps_per_pkg = mean(map(lambda r: r.ndeps, results))
    print("Average number of dependencies in package: %g" % (deps_per_pkg / npkgs))

    syms_per_pkg = mean(map(lambda r: r.nsyms, results))
    print("Average number of symbols in package: %g" % (syms_per_pkg / npkgs))

    num_fails = sum(map(lambda r: r.has_errors, results))
    print("Number of failed packages: %d" % num_fails)

  parallel_map.raise_errors(exc_lists)

if __name__ == '__main__':
  main()
