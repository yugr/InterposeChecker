# The MIT License (MIT)
# 
# Copyright (c) 2018 Yury Gribov
# 
# Use of this source code is governed by The MIT License (MIT)
# that can be found in the LICENSE.txt file.

import sys

class Error(Exception):
  def __init__(self, message):
    super(Error, self).__init__(message)
    self.message = message

prog_name = None

def set_prog_name(value):
  global prog_name
  prog_name = value

def warn(msg):
  sys.stderr.write('%s: warning: %s\n' % (prog_name, msg))

raise_on_error = False

def enable_raise_on_error(value=True):
  global raise_on_error
  raise_on_error = value

def error(msg):
  sys.stderr.write('%s: error: %s\n' % (prog_name, msg))
  if raise_on_error:
    raise Error(msg)
  else:
    sys.exit(1)

def fatal_error(msg):
  sys.stderr.write('%s: fatal error: %s\n' % (prog_name, msg))
  sys.exit(1)
