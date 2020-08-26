Included in this directory are two patch files to hook `UMASH` into
[Reini Urban's SMHasher](https://github.com/rurban/smhasher), and into 
[Yves Orton's older branch](https://github.com/demerphq/smhasher).

Copy `umash.[ch]` in the toplevel SMHasher source directory, and apply
either `0001-Hook-UMASH-in-rurban-s-SMHasher.patch` or
`0001-Hook-UMASH-in-demerphq-s-SMHasher.patch`.

You may notice that the verification values differ from the logs here.
That's due to a last minute change to `umash_params_derive`, in order
to help out any eventual big endian port.  That function is only used
to generate parameters, and the change does not affect UMASH's
performance or quality.  I'll get around to fixing that soon.
