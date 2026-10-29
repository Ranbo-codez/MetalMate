# Changelog

## 1.4.0 (2026-10-29): first public release

MetalMate by Ranbir Dhall, now public: free for non-commercial use under the PolyForm Noncommercial
License 1.0.0, with the full source code.

### Following the game
- **No more phantom moves.** A new position has to show up in two screenshots before it counts, so a
  piece caught mid-slide is never recorded as a move (this used to make the record, and then the arrows,
  go wrong).
- **No more stuck arrows.** When MetalMate isn't sure of the position for more than a moment, it clears the
  arrows and says "Catching up…" instead of leaving old suggestions on the board. A screenshot that doesn't
  match is looked at again within a fifth of a second.
- **Faster replies.** While waiting for the opponent's move, MetalMate looks twice a second, so the arrows
  for your reply appear sooner.
- **Steadier arrows.** The helper that draws them restarts by itself if it ever stops, putting back what
  was on screen, and never holds up the rest of the app.
- Boards that are found but can't be read no longer trigger a search every few seconds; a few screenshots
  are kept automatically so the problem can be reported.
- Stockfish's memory (hash) is capped by your Mac's RAM, so a large setting can't slow the whole Mac down.

### Other changes
- MetalMate's chess rules, notation, PGN and engine communication are now its own code.
- The app no longer ships an engine of its own; Stockfish and the engines in the *Discover* tab are used.
  An engine registered by an older build is removed automatically.
- Built for Apple Silicon Macs with macOS 12 or later, and downloadable as a DMG.

## 1.3.0 and earlier

Private builds. Highlights: multiple engines and profiles with the *Discover* tab, the game library with
groups and PGN export, statistics, spoken moves, global shortcuts, a menu-bar icon and the setup guide.
