# The MIT License (MIT)
# 
# Copyright (c) 2018 Yury Gribov
# 
# Use of this source code is governed by The MIT License (MIT)
# that can be found in the LICENSE.txt file.

import MySQLdb

def connect(db_name=None):
  args = dict(
    host='localhost',
    user='root',
    passwd='password',
  )
  if db_name is not None:
    args['db'] = db_name
  return MySQLdb.connect(**args)

def connect_for_bulk_inserts(db_name=None):
  conn = connect(db_name)
  with conn as cur:
    # Optimizations from https://dev.mysql.com/doc/refman/5.5/en/optimizing-innodb-bulk-data-loading.html
    # and https://dev.mysql.com/doc/refman/5.7/en/insert-optimization.html
    cur.execute('SET foreign_key_checks=0')
    cur.execute('SET unique_checks=0')
#    cur.execute('SET innodb_autoinc_lock_mode=0')
    cur.execute('SET GLOBAL innodb_flush_log_at_trx_commit=2')
    # Autotrimming
    cur.execute("SET SESSION sql_mode=''")
  return conn

def create_db(db_name):
  conn = connect(db_name)
  with conn as cur:
    cur.execute('DROP DATABASE %s' % db_name)
  with conn as cur:
    cur.execute('CREATE DATABASE %s' % db_name)
  conn.close()

def maybe_create_key(cur, table, keys):
  idx_name = table + ''.join(keys) + 'Idx'
  cur.execute('SHOW INDEX FROM %s' % table)
  idx_names = map(lambda idx: idx[2], cur.fetchall())
  if idx_name not in idx_names:
    cur.execute('CREATE INDEX %s ON %s (%s)' % (idx_name, table, ', '.join(keys)))
