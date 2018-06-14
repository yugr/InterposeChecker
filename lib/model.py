# The MIT License (MIT)
# 
# Copyright (c) 2018 Yury Gribov
# 
# Use of this source code is governed by The MIT License (MIT)
# that can be found in the LICENSE.txt file.

from lib import database
from lib import errors
from lib.errors import warn

class Package:
  def __init__(self, name, source_name=None):
    self.name = name
    self.source_name = source_name
    self.lst = []

    self.id = None
    self.has_errors = False

  def __repr__(self):
    lst = '\n'.join(map(lambda x: '  ' + x, self.lst))
    return '%s (%s):\n%s' % (self.name, self.source_name, lst)

  @classmethod
  def create_schema(cls, cur):
    cur.execute('CREATE TABLE Packages (ID INT UNSIGNED NOT NULL AUTO_INCREMENT, Name VARCHAR(64), SourceName VARCHAR(32), PRIMARY KEY (ID))')
    cur.execute('CREATE TABLE Errors (PackageID INT UNSIGNED, Message VARCHAR(1024), FOREIGN KEY (PackageID) REFERENCES Packages(ID))')

  def serialize(self, cur, error_msg):
    source_name = '' if self.source_name is None else self.source_name
    cur.execute('INSERT INTO Packages (Name, SourceName) VALUES (%s, %s)', (self.name, source_name))
    self.id = int(cur.lastrowid)
    if error_msg:
      cur.execute('INSERT INTO Errors (PackageID, Message) VALUES (%s, %s)', (self.id, error_msg))

  @classmethod
  def create_indices(cls, cur):
    database.maybe_create_key(cur, 'Packages', ['Name'])
    database.maybe_create_key(cur, 'Errors', ['PackageID'])

  @classmethod
  def deserialize(cls, cur, name):
    cur.execute('SELECT * FROM Packages WHERE Name = "%s"' % name)
    pkg = None
    for ID, name, source_name in cur.fetchall():
      if pkg is not None:
        errors.fatal_error("found multiple packages named '%s'" % name)
      pkg = Package(name, source_name)
      pkg.id = ID
    if pkg is None:
      errors.fatal_error("found no package named '%s'" % name)
    return pkg

  @classmethod
  def deserialize_all(cls, cur):
    cur.execute('SELECT * FROM Packages')
    pkgs = []
    for ID, name, source_name in cur.fetchall():
      pkg = Package(name, source_name)
      pkg.id = ID
      cur.execute('SELECT COUNT(*) FROM Errors WHERE PackageID = %d' % ID)
      row = cur.fetchone() 
      if row[0] != 0:
        pkg.has_errors = True
      pkgs.append(pkg)
    return pkgs

class Object:
  def __init__(self, name, soname, pkg, deps, imports, exports, is_shlib, is_symbolic):
    self.name = name
    self.soname = soname
    self.pkg = pkg
    self.deps = deps
    self.imports = imports
    self.exports = exports
    self.is_shlib = is_shlib
    self.is_symbolic = is_symbolic

    self.id = None

    # A workaround for not modelling sym versions.
    self.filter_dups(self.imports)
    self.filter_dups(self.exports)

  def __repr__(self):
    return """\
%s %s (DT_SONAME %s):
  DT_NEEDED: %s
  imports: %s
  exports: %s
  symbolic: %d
""" % ('Shlib' if self.is_shlib else 'Executable', self.name, self.soname, self.deps,
       self.imports, self.exports, self.is_symbolic)

  # Suppress warnings for e.g. _sys_nerr@@GLIBC_2.12 and _sys_nerr@GLIBC_2.4
  def filter_dups(self, sym_list):
    lst = []
    lst_names = set()
    for sym in sym_list:
      if sym.name not in lst_names:
        lst_names.add(sym.name)
        lst.append(sym)
    sym_list[:] = lst

  @classmethod
  def create_schema(cls, cur):
    cur.execute('CREATE TABLE Objects (ID INT UNSIGNED NOT NULL AUTO_INCREMENT, Name VARCHAR(128), SoName VARCHAR(128), IsShlib BOOLEAN, IsSymbolic BOOLEAN, PackageID INT UNSIGNED, PRIMARY KEY (ID), FOREIGN KEY (PackageID) REFERENCES Packages(ID))')
    cur.execute('CREATE TABLE ShlibDeps (ObjectID INT UNSIGNED, DepName VARCHAR(64), FOREIGN KEY (ObjectID) REFERENCES Objects(ID))')

  def serialize(self, cur, pkg_id):
    soname = '' if self.soname is None else self.soname
    cur.execute('INSERT INTO Objects (Name, SoName, IsShlib, IsSymbolic, PackageID) VALUES (%s, %s, %s, %s, %s)', (self.name, soname, self.is_shlib, self.is_symbolic, pkg_id))
    self.id = int(cur.lastrowid)
    cur.executemany('INSERT INTO ShlibDeps (ObjectID, DepName) VALUES (%s, %s)', [(self.id, dep) for dep in self.deps])
    cur.executemany('INSERT INTO Symbols (Name, Version, IsWeak, IsProtected, ImportOrExport, ObjectID) VALUES (%s, %s, %s, %s, %s, %s)',
                    [(sym.name, sym.version, sym.is_weak, sym.is_protected, i < len(self.imports), self.id)
                     for i, sym in enumerate(self.imports + self.exports)])

  @classmethod
  def create_indices(cls, cur):
    # TODO: join them?
    database.maybe_create_key(cur, 'Objects', ['SoName'])
    database.maybe_create_key(cur, 'Objects', ['PackageID'])
    database.maybe_create_key(cur, 'ShlibDeps', ['ObjectID'])

  @classmethod
  def deserialize_pkg_objects(cls, cur, pkg):
    cur.execute('SELECT * FROM Objects WHERE PackageID = %d AND IsShlib = FALSE' % pkg.id)
    objects = []
    for ID, name, soname, is_shlib, is_symbolic, _ in cur.fetchall():
      obj = Object(name, soname, pkg, [], [], [], is_shlib, is_symbolic)
      obj.id = ID
      objects.append(obj)
    return objects

  def deserialize_deps(self, cur):
    if not hasattr(Object.deserialize_deps, 'warned_sonames'):
      Object.deserialize_deps.warned_sonames = set()
    self.deps = []
    cur.execute('SELECT Objects.ID, Objects.Name, SoName, IsShlib, IsSymbolic, Packages.ID, Packages.Name, Packages.SourceName FROM (Objects INNER JOIN ShlibDeps ON Objects.SoName = ShlibDeps.DepName INNER JOIN Packages ON Objects.PackageID = Packages.ID) WHERE ShlibDeps.ObjectID = %d' % self.id)
    soname_origins = {}
    for ID, obj_name, soname, is_shlib, is_symbolic, pkg_id, pkg_name, pkg_source_name in cur.fetchall():
      if soname in soname_origins and soname not in Object.deserialize_deps.warned_sonames:
        orig_obj_name, orig_pkg_name = soname_origins[soname]
        warn("duplicate implementations of SONAME '%s': %s (from %s) and %s (from %s)" % (soname, obj_name, pkg_name, orig_obj_name, orig_pkg_name))
        Object.deserialize_deps.warned_sonames.add(soname)
        continue
      soname_origins[soname] = obj_name, pkg_name
      pkg = Package(pkg_name, pkg_source_name)
      pkg.id = pkg_id
      obj = Object(obj_name, soname, pkg, [], [], [], is_shlib, is_symbolic)
      obj.id = ID
      obj.deserialize_deps(cur)  # TODO: circular deps
      self.deps.append(obj)

class Symbol:
  def __init__(self, name, obj, is_weak, is_protected):
    self.name = name
    self.obj = obj
    self.is_weak = is_weak
    self.is_protected = is_protected
    self.version = 0  #TODO

    self.id = None

  def __repr__(self):
    s = ["Symbol %s%s (in object %s)" % (self.name, ('@' + self.version) if self.version else '', self.obj.name)]
    if self.is_weak:
      s.append('weak')
    if self.is_protected:
      s.append('protected')
    return ' '.join(s)

  def create_schema(cur):
    cur.execute('CREATE TABLE Symbols (ID INT UNSIGNED NOT NULL AUTO_INCREMENT, Name VARCHAR(1024), Version VARCHAR(32), IsWeak BOOLEAN, IsProtected BOOLEAN, ImportOrExport BOOLEAN, ObjectID INT UNSIGNED, PRIMARY KEY (ID), FOREIGN KEY (ObjectID) REFERENCES Objects(ID))')

  @classmethod
  def create_indices(cls, cur):
    database.maybe_create_key(cur, 'Symbols', ['ObjectID'])

  @classmethod
  def deserialize_syms(cls, cur, obj):
    cur.execute('SELECT ID, Name, IsWeak, IsProtected, ImportOrExport FROM Symbols WHERE ObjectID = %d' % obj.id)
    imports = []
    exports = []
    for ID, name, is_weak, is_protected, import_or_export in cur.fetchall():
      sym = Symbol(name, obj, is_weak, is_protected)
      sym.id = ID
      if import_or_export:
        imports.append(sym)
      else:
        exports.append(sym)
    return imports, exports

def create_schema(db_name=None):
  database.create_db(db_name)
  conn = database.connect(db_name)
  with conn as cur:
    Package.create_schema(cur)
    Object.create_schema(cur)
    Symbol.create_schema(cur)
  conn.close()
