#!/usr/bin/python3

# The MIT License (MIT)
# 
# Copyright (c) 2018 Yury Gribov
# 
# Use of this source code is governed by The MIT License (MIT)
# that can be found in the LICENSE.txt file.

import os
import os.path
import re
import sys
import argparse
import datetime

from lib import database
from lib.errors import (error, warn, set_prog_name)
from lib.model import (Package, Object, Symbol)
from lib import linker
from lib import parallel_map
from lib.analysis import mean

def deserialize_deps_and_syms(obj, cur, lib_map):
  if not hasattr(deserialize_deps_and_syms, 'warned'):
    deserialize_deps_and_syms.warned = set()

  obj.imports, obj.exports = Symbol.deserialize_syms(cur, obj)

  obj.deserialize_deps(cur)

  new_deps = []
  for dep_obj in obj.deps:
    if dep_obj.soname is None:
      warn("object %s does not have a SONAME, skipping..." % dep_obj.soname)
    if dep_obj.soname in lib_map:
      old_obj = lib_map[dep_obj.soname]
      if old_obj.name != dep_obj.name and dep_obj.soname not in deserialize_deps_and_syms.warned:
        deserialize_deps_and_syms.warned.add(dep_obj.soname)
        warn("libraries %s and %s have same soname %s" % (old_obj.name,
                                                          dep_obj.name,
                                                          dep_obj.soname))
      dep_obj = old_obj
    else:
      deserialize_deps_and_syms(dep_obj, cur, lib_map)
      new_deps.append(dep_obj)
      if dep_obj.soname is not None:
        lib_map[dep_obj.soname] = dep_obj
    new_deps.append(dep_obj)
  obj.deps = new_deps

def can_ignore_unres(sym, obj, main_obj):
  # These functions are provided to libthread_db by gdb
  if sym.name.startswith('ps_') and obj.name.startswith('libthread_db'):
    return True
  # Perl libs import symbols from executable
  if re.match(r'^(Perl|PL)', sym.name) and obj.pkg.name.startswith('perl'):
    return True
  # OpenGL is often loaded at runtime via dlopen
  if re.match(r'^(egl|gl|glut)[A-Z]', sym.name):
    return True
  return False

def can_ignore_dup(sym, obj, other_obj):
  # Ignore symbols within the same package
  # as implementations are likely to be identical.
  if obj.pkg.source_name is not None and obj.pkg.source_name == other_obj.pkg.source_name:
    return True
  if obj.pkg.source_name.startswith(other_obj.pkg.source_name) \
      or other_obj.pkg.source_name.startswith(obj.pkg.source_name):
    return True
  # Ld.so duplicates some functions from libc
  # TODO: why does it export them?
  if (linker.is_dynamic_linker(obj.name) and linker.is_libc(other_obj.name)) \
      or (linker.is_dynamic_linker(other_obj.name) and linker.is_libc(obj.name)):
    return True
  # Parts of libc contain dup symbols
  # TODO: why?
  if linker.is_libc_sublib(obj.name) and linker.is_libc_sublib(other_obj.name):
    return True
  # Known issue in GCC: https://gcc.gnu.org/ml/gcc-help/2018-04/msg00097.html
  if sym.name in ('_init', '_fini'):
    return True
  # Known issue in Bintools: https://sourceware.org/ml/binutils/2018-05/msg00012.html
  if sym.name in ('__bss_start', '_edata', '_etext', '__etext', '_end'):
    return True
  return False

def find_interposes(pkg, conn, v):
  if not hasattr(find_interposes, 'dup_warnings'):
    find_interposes.dup_warnings = set()
    find_interposes.soname_warnings = set()

  # TODO: thread-local cache for most commonly used libs?
  with conn as cur:
    pkg_objects = Object.deserialize_pkg_objects(cur, pkg)
    lib_map = {}
    for obj in pkg_objects:
      deserialize_deps_and_syms(obj, cur, lib_map)

  for pkg_obj in pkg_objects:
    # Build library load list
    lib_list = [pkg_obj]
    loaded_sonames = set()
    pending_libs = pkg_obj.deps
    while pending_libs:
      new_pending_libs = []
      for obj in pending_libs:
        # TODO: check soname is present for libs
        if obj.soname is None and (pkg.name, obj.name) not in find_interposes.soname_warnings:
          warn("library %s does not have a SONAME" % obj.name)
          find_interposes.soname_warnings.add((pkg.name, obj.name))
        elif obj.soname not in loaded_sonames:
          lib_list.append(obj)
          loaded_sonames.add(obj.soname)
          new_pending_libs += obj.deps
      pending_libs = new_pending_libs

    if v:
      print("Library list for object %s in package %s:" % (pkg_obj.name, pkg.name))
      for obj in lib_list:
        print("  object %s:" % obj.name)
        for sym in obj.exports:
          print("    %s" % sym.name)

    # Collect definitions and report interpositions
    # TODO: report interposition only if there's an actual use for it?
    sym_origins = {}
    for obj in lib_list:
      for sym in obj.exports:
        if sym.name not in sym_origins:
          sym_origins[sym.name] = obj
          continue
        other_obj = sym_origins[sym.name]
        if not can_ignore_dup(sym, obj, other_obj) \
            and (sym.name, obj.name, other_obj.name) not in find_interposes.dup_warnings:
          print("Duplicate definition of symbol '%s' in modules %s (from package %s) and %s (from package %s) (when loading object %s in package %s)"
                % (sym.name, other_obj.name, other_obj.pkg.source_name, obj.name, obj.pkg.source_name, pkg_obj.name, pkg.name))
          find_interposes.dup_warnings.add((sym.name, obj.name, other_obj.name))
          find_interposes.dup_warnings.add((sym.name, other_obj.name, obj.name))

    # Resolve symbols
    ref_origins = {}
    for obj in lib_list:
      for sym in obj.imports:
        if sym.name not in sym_origins and not sym.is_weak and not can_ignore_unres(sym, obj, pkg_obj):
          warn("unresolved reference to symbol '%s' in library %s (from package %s) (when loading object %s in package %s)"
                % (sym.name, obj.name, obj.pkg.source_name, pkg_obj.name, pkg.name))

class Stats:
  def __init__(self, time):
    self.time = time

def main():
  parser = argparse.ArgumentParser(description="Analyze contents of Debian binary packages and store them to database.")
  parser.add_argument('--verbose', '-v', action='count', help="Print diagnostic info.", default=0)
  parser.add_argument('--db-name', help="Database name.", default='syms')
  parser.add_argument('-j', dest='num_threads', help="Number of threads.", type=int, default=2)
  parser.add_argument('--stats', dest='stats', help="Print statistics before exit.", default=False, action='store_true')
  parser.add_argument('--no-stats', dest='stats', help="Do not print statistics before exit.", action='store_false')
  parser.add_argument('--allow-errors', dest='allow_errors', help="Process packages which had errors.", default=False, action='store_true')
  parser.add_argument('--no-allow-errors', dest='allow_errors', help="Do not process packages which had errors.", action='store_false')
  parser.add_argument('pkgs', metavar='PKGS', nargs='*', help="Optional list of packages to analyze (default is to analyze all).")
  parser.set_defaults(stats=True)

  args = parser.parse_args()

  set_prog_name(os.path.basename(__file__))

  conn = database.connect(args.db_name)

  with conn as cur:
    Package.create_indices(cur)
    Object.create_indices(cur)
    Symbol.create_indices(cur)

  if not args.pkgs:
    with conn as cur:
      pkgs = Package.deserialize_all(cur)
  else:
    pkgs = []
    for pkg_name in args.pkgs:
      with conn as cur:
        pkgs.append(Package.deserialize(cur, pkg_name))
  conn.close()

  if not args.allow_errors:
    pkgs = list(filter(lambda p: not p.has_errors, pkgs))

  def do_work(pkg, ctx):
    t1 = datetime.datetime.now()
    if ctx[0] is None:
      ctx[0] = database.connect(args.db_name)
    conn = ctx[0]
    find_interposes(pkg, conn, args.verbose)
    t2 = datetime.datetime.now()
    time = (t2 - t1).total_seconds()
    return Stats(time)

  res_lists, exc_lists = parallel_map.map(do_work, pkgs, args.num_threads)

  if args.stats:
    print("Number of packages: %d" % len(pkgs))

    results = [r for lst in res_lists for r in lst]
    wall_time = max(sum(r.time for r in lst) for lst in res_lists)
    print("Wall time: %d:%d" % (wall_time / 60, wall_time % 60))

    times = [r.time for r in results]
    print("Average time to process a package: %g sec." % mean(times))

  parallel_map.raise_errors(exc_lists)

if __name__ == '__main__':
  main()
