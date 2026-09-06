# storecheck

Does this app meet the App Store and Google Play rules, and how do we know?

Point it at an app directory. It reads what the stores read, the built
package and the files around it, never the source code and never caring what
the app was built with. It fetches the current rule pages and proves they have
not changed since they were last read. It checks every rule that can be checked
by a machine with no model involved, hands the judgement questions to whatever
model you attach, runs a second pass whose only job is to break the first, and
writes one grid where every row says how its verdict is known.

It never stores the stores' own policy text. Only a page's address, the date it
was read, a hash of its text, our own paraphrase, and at most one short quote.

    python3 -m storecheck audit /path/to/app
    python3 -m storecheck self-test
    python3 -m unittest

Python 3.11 or later, standard library only.

See PLAN.md for what exists and what is next.
