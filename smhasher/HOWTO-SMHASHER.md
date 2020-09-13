Reini Urban included `UMASH` in his fork of SMHasher on
[August 25, 2020](https://github.com/rurban/smhasher/commit/05620cd5dff2eb06ad8b7596a9bc94299d9eb209).
Simply clone the repository, and overwrite `umash.[ch]` as
needed.

This directory includes a patch files to hook `UMASH` into
[Yves Orton's older branch](https://github.com/demerphq/smhasher).
Copy `umash.[ch]` in the toplevel SMHasher source directory, and apply
`0001-Hook-UMASH-in-demerphq-s-SMHasher.patch`.

Reini Urban's fork has more up-to-date hashes to compare with, and
includes additional "end-to-end" hash table speed tests.  Yves Orton's
fork is still interesting for its more extensive statistical testing.

The `demerphq` fork does not build cleanly.  One has to execute
`make_smhasher` to generate the `VERSION.h` file.  Although the script
fails, it does so after generating `VERSION.h`, which suffices for
`build.sh` to succeed.

You may notice that the verification values differ from the logs here.
That's due to a last minute change to `umash_params_derive`, in order
to help out any eventual big endian port.  That function is only used
to generate parameters, and the change does not affect UMASH's
performance or quality.  I'll get around to fixing that soon.
