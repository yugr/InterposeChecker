# What is this?

This is an UNFINISHED experimental project to locate symbol interpositions in Debian packages.

Inspired by [Flameeyes' link-collisions script](https://github.com/Flameeyes/ruby-elf/tree/master/tools/link-collisions).

# Usage

First of all install prerequisites:
```
$ sudo apt-get install mysql-server mysql-client python3-mysqldb
$ pip3 install pyelftools python-magic
```

Then update APT database:
```
$ sudo apt-get update
```
and generate up-to-date package list:
```
$ ./download_pkg_list.py > pkgs.lst
```

Finally extract relevant subset from `pkgs.lst` (e.g. via `find_deps.sh`) and run analysis
```
$ ./index_packages.py min.lst
$ ./find_interposes.py
```
(may need to update MySQL root password in `lib/database.py`).
