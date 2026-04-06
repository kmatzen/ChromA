Jaga's ChromA fork

A fork of ChromA with the goal of fixing bugs and incompatibilities in the original.  Based on the 2019-05-04 source.

### [▶ Try it in your browser](https://kmatzen.github.io/chroma/) — drop a .gb/.gbc ROM to play

Some notable hacks and games that have had issues fixed:
- Donkey Kong Land: New Colors Mode, https://www.romhacking.net/hacks/6076/ (file select menu accessible)
- Faceball 2000 (menu accessible)
- Kirby's Dream Land DX Service Repair, https://www.romhacking.net/hacks/6224/ (level 2 palette issues fixed)
- Konami GB Collections 2 and 4 (boots)
- Metal Gear Solid: Ghost Babel (elevator crash fixed)
- Pokemon Crystal (graphical corruption fixed)
- Wario Land DX, https://www.romhacking.net/hacks/6683/ (boots)

To build:
- Install the latest DevkitPro GBA tools
- Navigate Msys2 to this directory
- make
- Rename font.lz77.o to font.o and fontpal.bin.o to fontpal.o
- make

To test, I build a ROM with the resulting chroma.gba and the game I'm testing using chromafront.exe, then run it in mGBA.  You can find chromafront.exe as part of the ChromA releases.  For helpful debug symbols, take chroma.elf, put it in the same directory as the built ROM, and rename it to (ROM name).elf.  (Thanks to Endrift for the tip.)
Also included is a simple .bat file that will use gdb to dump debug symbols to a text file.

Thanks to:
- Dwedit for the ChromA emulator, which you can find at https://www.dwedit.org/gba/chromacolor.php.  If you'd like to incorporate my changes into ChromA, you're more than welcome to.
- FluBBa for the ChromA emulator before that: http://chroma.webpersona.com/
- Minucce for help with ASM and pointing me in the right direction.
- Sterophonick for code tweaks and featuring ChromA in the excellent Simple kernel for the EZ-Flash Omega carts: https://gbatemp.net/threads/new-theme-for-ez-flash-omega.520665/
- EZ-Flash for releasing the source to their modified ChromA builds, which hopefully allows this to support the Omega Definitive Edition's rumble features
- Nuvie for the code that saves the desired Game Boy type per game.
- Radimerry for the MGS:Ghost Babel elevator fix, Faceball menu fix, and SMLDX SRAM fix.
- Therealteamplayer for the default-to-grayscale code for GB games if no SGB palette is found.