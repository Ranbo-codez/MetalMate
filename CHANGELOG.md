# Changelog

## 1.4.3 (2026-11-04)

Found by playing real games against chess.com's bots with MetalMate watching.

- **No more unreadable boards after a new game starts.** chess.com spins the pieces into place at the start of
  a game; MetalMate could learn the board from a frame where the pieces were sideways and then couldn't read
  it. It now learns a board only once two looks in a row agree.
- **Keeps up when the board moves on the page.** When a game starts chess.com moves the board (the player
  names appear above it). MetalMate kept reading the old spot for up to 20 seconds, so the arrows were late or
  missing. It now notices straight away that the squares no longer line up and finds the board again.
- **Switching sites works before a board is learned.** Changing from chess.com to a Lichess tab (whose board
  sits elsewhere on the page) left MetalMate looking at the old spot; it now finds the new board and learns it.

## 1.4.2 (2026-11-02)

- **Guides on chess.com (and other sites) work again.** If the board moved on the page (chess.com moves it
  when you go from the home page to a game) just as MetalMate learned it, it learned from a screenshot that
  was off by part of a square. Every piece then looked wrong, so no guides appeared ("I can see the board
  but can't read the pieces"). MetalMate now checks that a board is lined up with its squares before
  learning it, finds the board again if it isn't, and re-learns a board it can't read by itself as soon as
  it shows the starting position.

## 1.4.1 (2026-10-31)

- **Every engine installs in one click, with nothing else to install.** Downloads failed in the 1.4.0
  app with a certificate error; they now use your Mac's own trusted certificates. Leela Chess Zero and
  GNU Chess no longer need Homebrew: MetalMate downloads Homebrew's ready-made packages directly
  (checked against their published checksums), and Stockfish comes from its official release.
- **Relaunch works.** After granting Screen Recording, *Relaunch MetalMate* now reopens the app instead of
  just quitting.
- **Sharp Dock icon.** The icon no longer turns blurry while MetalMate is open.
- **No more stuck "Engine problem".** After installing the first engine, the warning in the sidebar now
  clears straight away.

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
