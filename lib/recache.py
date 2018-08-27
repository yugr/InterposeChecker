# The MIT License (MIT)
# 
# Copyright (c) 2018 Yury Gribov
# 
# Use of this source code is governed by The MIT License (MIT)
# that can be found in the LICENSE.txt file.

import re

# "Regex cacher" which allows doing things like
#   if Re.match(...):
#     x = Re.group(1)
class Re:
  last_match = None

  @classmethod
  def match(cls, *args, **kwargs):
    cls.last_match = re.match(*args, **kwargs)
    return cls.last_match

  @classmethod
  def search(cls, *args, **kwargs):
    cls.last_match = re.search(*args, **kwargs)
    return cls.last_match

  @classmethod
  def fullmatch(cls, *args, **kwargs):
    cls.last_match = re.fullmatch(*args, **kwargs)
    return cls.last_match

  @classmethod
  def group(cls, *args, **kwargs):
    return cls.last_match.group(*args, *kwargs)

  @classmethod
  def groups(cls, *args, **kwargs):
    return cls.last_match.groups(*args, **kwargs)
