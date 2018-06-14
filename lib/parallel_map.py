# The MIT License (MIT)
# 
# Copyright (c) 2018 Yury Gribov
# 
# Use of this source code is governed by The MIT License (MIT)
# that can be found in the LICENSE.txt file.

import threading
import queue
import multiprocessing

from lib.errors import warn

class WorkerThread(threading.Thread):
  def __init__(self, q, action):
    threading.Thread.__init__(self)
    self.q = q
    self.exceptions = []
    self.action = action
    self.ctx = [None]
    self.results = []

  def run(self):
    try:
      while not self.q.empty():
        item = None
        try:
          item = self.q.get(False)
          result = self.action(item, self.ctx)
          self.results.append(result)
        except queue.Empty:
          pass
        finally:
          if item:
            self.q.task_done()
    except Exception as e:
      self.exceptions.append(e)

def serial_map(fun, tasks, num_threads):
  results = []
  ctx = []
  try:
    for task in tasks:
      result = fun(task, ctx)
      results.append(result)
  except Exception as e:
    exceptions = [e]
  return results, exceptions

def map(fun, tasks, num_threads):
  if num_threads is None:
    ncpu = multiprocessing.cpu_count()
    num_threads = int((1.5 * ncpu) if ncpu > 1 else 2)

  q = queue.Queue(maxsize=0)
  for task in tasks:
    q.put(task)

  workers = []
  for i in range(num_threads):
    w = WorkerThread(q, fun)
    workers.append(w)
    w.start()

  for w in workers:
    w.join()

  results = [w.results for w in workers]
  exceptions = [w.exceptions for w in workers]

  return results, exceptions

def raise_errors(exc_lists):
  E = None
  for i, lst in enumerate(exc_lists):
    for e in lst:
      warn("exception in thread %d: %s" % (i, e))
      E = e
  if E is not None:
    raise E
