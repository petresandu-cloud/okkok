# Okkok, the brand

The tool in this repository is published as open source under the AGPL. The
name **Okkok**, the gate-and-check mark and the wordmark are not: they are
trademarks of Editerra AB, and the licence grants no right to use them. Anyone
may fork the code; only Editerra AB may call the result Okkok. That is the
line between the open code and the commercial product, and it is the same
line Mozilla draws around Firefox and Docker around its whale.

## The name

**Okkok.** Five letters, two syllables, said "OK, OK".

Where it comes from: two OKs, one for each store, joined by a K for
*kontroll*, the Swedish word for check. The App Store says OK, Google Play
says OK, and the check in the middle is what earns them. Read the wordmark
as OK · K · OK. Editerra AB is a Swedish company, and the word keeps that.

It is a coined word: no dictionary meaning, no company, no product, no
package on PyPI or npm carried it when it was chosen on 8 September 2026.

Write it *Okkok* in prose and *okkok* in the wordmark and in commands. Never
OKKOK, never Ok-Kok, never with a space.

The package and the command may keep a plain technical name; the brand is the
product people see, buy support for, and get signed reports from.

## The line

**OK for the App Store. OK for Google Play. Okkok.**

Shorter, under the wordmark: **Store compliance check.** That is also the title
every report carries, so the report and the brand say the same thing.

## The mark

A rounded square, the shape of an app icon, holding a gate: two posts and a
lintel. Inside the gate, a check. The app is at the gate; the check is what
lets it through.

- `assets/okkok-mark.svg`: the mark in colour. Petrol ground, white gate,
  mint check.
- `assets/okkok-mark-mono.svg`: one colour, for print, favicons, and dark
  grounds (it takes `currentColor`).
- `assets/okkok-logo.svg`: mark and wordmark side by side with the line
  under it. Outline the text before print use; the file names a system
  font stack so it renders everywhere but is not a typeface licence.

Keep the mark whole: no recolouring beyond the two versions here, no
rotation, no effects, nothing placed inside the gate but the check. Minimum
size 16 pixels; at that size the mono version reads better.

## Colour

| Role | Value | Use |
|---|---|---|
| Petrol | `#0F5C6E` | the brand ground, the wordmark on light pages where ink is too heavy |
| Mint | `#9BE7C4` | the check, and nothing else |
| Ink | `#141414` | text |
| Paper | `#FFFFFF` | ground |

The five status colours in the report (red, amber, blue, grey, green) are
semantic, fixed by `REPORT-PRINCIPLES.md`, and are not brand colours. The
brand never uses them and they never carry the brand.

## Type

The wordmark is set heavy, tight and lowercase. In documents and on the web,
the reader's system sans serif, as the report does; the brand does not ship
a typeface. Where a display face is wanted for marketing, choose a geometric
sans with a single-storey *a* so it sits with the wordmark.

## Voice

Plain sentences. Findings, not opinions. What was found, what to do, who does
it, where, and how we know. No exclamation marks, no promises about approval:
the stores decide, Okkok tells you where you stand before they do.

## What is commercial

The code stays free under the AGPL. What Editerra AB sells around the name:

- **Signed reports.** A report produced through Editerra's service carries a
  signature verifiable with Editerra's public key. A fork can produce a page
  that looks the same; it cannot produce that signature. This is the only
  mark that cannot be stripped, because the key never ships with the code.
- **A commercial licence** for building the engine into a closed product or
  a hosted service (see `COMMERCIAL-LICENSE.md`).
- **Maintained rule sets and support** under an agreement.

## Ownership marks in the code

Every source file opens with the copyright and the SPDX licence line. The
package metadata names Editerra AB as author and carries the licence
expression. Every generated report carries a `generator` meta tag naming the
tool, its version and the licence holder, and the same line in its footer.
These are honest, greppable and legally meaningful. None of them is hidden
and none is immutable: open code can be edited by anyone, and a mark that
claimed otherwise would be a lie. What stops a stripped copy being sold as
Okkok is the trademark, not a watermark.

## Trademark notice

Okkok, the gate-and-check mark and the okkok wordmark are trademarks of
Editerra AB, Org.nr 559441-6454, Sweden. Registration is the owner's next
step; until then they are protected as unregistered marks by use. Contact:
contact@editerra.se.
