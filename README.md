# 🧁 bitcoin-notes

Welcome! This is my personal stash of notes on Bitcoin Core and some related C++ things I run into while digging around. These are mostly for myself, but you're welcome to snoop around.

Notes may be _wrong_, _outdated_, or just me thinking out loud. Don't trust, verify! :)

## Table of Contents

### 🫧 c++/
- [`default-arguments.md`](c++/default-arguments.md): C++ default arguments — syntax, header/source split, and usage examples.
- [`include-guards.md`](c++/include-guards.md): How include guards prevent multiple inclusion in C++ headers, and how to write them.
- [`macro-safety-do-while-false-idiom.md`](c++/macro-safety-do-while-false-idiom.md): Why macros use do { ... } while(false); to behave like safe single statements.
- [`mutex-vs-recursive-mutex.md`](c++/mutex-vs-recursive-mutex.md): Comparing std::mutex and std::recursive_mutex, with a hands-on nested logging example.
- [`pimpl_vs_pure_abstract.md`](c++/pimpl_vs_pure_abstract.md): Explains the PIMPL and Pure Abstract Class patterns for hiding implementation details.

### 🫧 p2p/
- [`addr-message.md`](p2p/addr-message.md): When, why, and how Bitcoin nodes send ADDR messages to peers
- [`addr-timestamps.md`](p2p/addr-timestamps.md): How address timestamps are initialized, updated, and used to evaluate freshness and "terribleness".
- [`getaddr-request.md`](p2p/getaddr-request.md): When and why nodes send GETADDR, and how responses are rate-limited.


---

Built with 🧁☕, curiosity, and a lot of `git grep`.

(Plus a little AI help to keep things organized.)

