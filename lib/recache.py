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
  def match(self, *args, **kwargs):
    self.last_match = re.match(*args, **kwargs)
    return self.last_match

  @classmethod
  def search(self, *args, **kwargs):
    self.last_match = re.search(*args, **kwargs)
    return self.last_match

  @classmethod
  def fullmatch(self, *args, **kwargs):
    self.last_match = re.fullmatch(*args, **kwargs)
    return self.last_match

  @classmethod
  def group(self, *args, **kwargs):
    return self.last_match.group(*args, *kwargs)

  @classmethod
  def groups(self, *args, **kwargs):
    return self.last_match.groups(*args, **kwargs)
