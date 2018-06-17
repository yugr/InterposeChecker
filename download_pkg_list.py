#!/usr/bin/python3

# The MIT License (MIT)
# 
# Copyright (c) 2018 Yury Gribov
# 
# Use of this source code is governed by The MIT License (MIT)
# that can be found in the LICENSE.txt file.

import io
import re
import urllib.request
import gzip

from lib.errors import (error, warn)
from lib.recache import Re

allpackages_url = 'https://packages.ubuntu.com/xenial/allpackages?format=txt.gz'

class PkgInfo:
  __slots__ = ['name', 'version', 'component', 'lst']

  def __init__(self, name, version, component=None):
    self.name = name
    self.version = version
    self.component = component
    self.lst = []

  def __repr__(self):
    lst = '\n'.join(map(lambda x: '  ' + x, self.lst))
    return '%s (%s) [%s]:\n%s' % (self.name, self.version, self.component, lst)

def get_packages():
  resp = urllib.request.urlopen(allpackages_url)
  if resp is None:
    error("failed to open %s" % allpackages_url)

  pkgs_file_compressed = io.BytesIO(resp.read())
  pkgs_file = gzip.GzipFile(fileobj=pkgs_file_compressed)
  lines = pkgs_file.read().decode('utf-8').split('\n')

  pkgs = []
  for l in lines:
    l = l.strip()
    if not l or 'virtual package provided by' in l:
      continue
    elif Re.match(r'^([0-9a-z_.\-+]+) (?:\(([0-9.\-]+)\))? *(?:\[([a-z0-9]+)\])?', l):
      pkgs.append(PkgInfo(Re.group(1), Re.group(2), Re.group(3)))
    elif pkgs:
      error("failed to parse package line: %s" % l)

  return pkgs

def main():
  for pkg in get_packages():
    # These packages cannot contain ELFs
    if re.search(r'-data\b|-dev$|-dbg$', pkg.name):
      continue
    print('%s %s %s'% (pkg.name, pkg.version, pkg.component))

if __name__ == '__main__':
  main()

