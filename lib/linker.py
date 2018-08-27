# The MIT License (MIT)
# 
# Copyright (c) 2018 Yury Gribov
# 
# Use of this source code is governed by The MIT License (MIT)
# that can be found in the LICENSE.txt file.

import re

def is_dynamic_linker(filename):
  return re.match(r'^ld-.*\.so$', filename)

def is_libc(filename):
  return filename.startswith('libc-')

def is_libc_sublib(filename):
  return re.match(r'^lib(c|m|rt|pthread)-', filename)
