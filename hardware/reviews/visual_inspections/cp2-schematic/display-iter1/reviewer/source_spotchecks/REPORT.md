# Display source spot-checks

## On-file object hashes
- PASS `615008145521.pdf`: `da03e4ed62572d59ba76a685b70fbcf613dd5a1fa37405537724dd34dd253c6e`
- PASS `USB4085-GF-A.pdf`: `e5e6f4f67ccaee397b33324fde439f7cdd273c5dd9048c48f096aae7029034be`
- PASS `ESP32-S3-WROOM-1-N16R8.pdf`: `27d71971da07c280c6068d08c74720d1a25b8f20cf8494dc1765bdd28d40d435`
- PASS `THVD1400DR.pdf`: `5ba9785d9fb8dc878b90fd196ff5faed27b5fff0ddfccb8346a82ac3c6a5c47f`
- PASS `R-78E3.3-0.5.pdf`: `d3855b95007832c025518b4ee2073697aabee0b6be311484ea9a1aa7b3c53b96`
- PASS `SMAJ_Diodes.pdf`: `70bd31105424570a6a076c3cb50a641cfe6245a1fe248f9086e2f5cfb1998440`
- PASS `MF-R025.pdf`: `ad20425ca080f8a15f5f81be1b0cc52b12365fbf99964d15fddfc75ba5301aed`

## Wurth J1 footprint
- PASS exact signal-pad map: `{'1': (0.0, 0.0, 0.9), '2': (-1.27, 2.54, 0.9), '3': (1.27, 2.54, 0.9), '4': (3.81, 2.54, 0.9), '5': (2.54, 0.0, 0.9), '6': (5.08, 0.0, 0.9), '7': (7.62, 0.0, 0.9), '8': (6.35, 2.54, 0.9)}`
- PASS x-order across both rows: `2,1,3,5,4,6,8,7`.
- PASS committed-blob SHA-256: `38db7c97fd9bb7becebf037c074fd3092e8d0f3115785f6aab3b921a7e899684`.
- Windows worktree SHA-256: `e477febf873d2f1a810a0e5db036383f5456111f0f85fc6722ff40ab1800abd1` (CRLF checkout).
- LF-normalized worktree SHA-256: `38db7c97fd9bb7becebf037c074fd3092e8d0f3115785f6aab3b921a7e899684`.
- Datasheet p1 identity: Wurth 615008145521, 8P8C horizontal shielded.
- Datasheet p1 hole pattern: 0.90 mm signal holes, 2.54 mm row separation, 1.27 mm stagger, 11.43 mm post span, 15.50 mm shield span.

## Citation checks
- PASS ESP32-S3-WROOM p11 Table 3-1: module pins 8/11/20/21/22 are RTC_GPIO15/18/12/13/14 respectively.
- PASS THVD1400 p3: pins 1..8 are R,/RE,DE,D,GND,A,B,VCC; /RE has 2 Mohm pull-up and DE has 2 Mohm pull-down.
- FAIL packet 15.6 says the THVD1400 bus absolute maximum is +/-18 V; TI p4 says VA/VB are -16 V to +16 V.
- PASS R-78E p1: R-78E3.3-0.5 is 6-28 V in, 3.3 V/0.5 A out, 220 uF maximum capacitive load.
- PASS SMAJ p2: SMAJ15A VC=24.4 V at 16.4 A and SMAJ12CA VC=19.9 V at 20.1 A.
- PASS MF-R025 p3: 5.1 +/-0.7 mm lead spacing and 0.51 mm lead diameter.

## USB4085 object identity
- On-file `USB4085-GF-A.pdf` identifies only family `USB4085`; it contains neither `GF-A` nor the ordering grid.
- The same-turn official GCT drawing (`USB4085_official_drawing.pdf`, SHA-256 `39afb82c5104579e8c2db4f4e758825c48cab1c4b06d4c61c62056470ff09e9e`) p1 defines `GF = Gold Flash` and `A = Tape & Reel`; p1/p2 call the part Dip/Through-Hole and show sixteen 0.65 mm PCB holes plus shell stakes.
- The installed KiCad `USB_C_Receptacle_GCT_USB4085` footprint uses through-hole pads for all sixteen contacts and the shell (`20` THT, `0` SMD pads).

## Result
- FAIL: 2 finding(s).
