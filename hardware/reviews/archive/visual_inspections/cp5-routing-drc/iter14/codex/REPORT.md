# Schematic Visual Audit Report

## Inputs
- Battery PDF: `/Users/pivot/Documents/repo/volthium_reader/hardware/reviews/visual_inspections/cp5-routing-drc/iter14/codex/snapshots/battery_schematic.pdf`
- Display PDF: `/Users/pivot/Documents/repo/volthium_reader/hardware/reviews/visual_inspections/cp5-routing-drc/iter14/codex/snapshots/display_schematic.pdf`

## Generated Artifacts
- Full-page renders: `*_full_300dpi.png`
- Dense-region crops: up to 12 per page (`*_crop_XX.png`)
- Snapshot copies: `snapshots/*.pdf`
- Integrity manifest: `MANIFEST.sha256`

## Word Extraction Counts
- Battery words: 547
- Display words: 446

### Battery schematic text-overlap findings
- Detected 206 overlapping word-box pairs.
- 1. p1: `GND` overlaps `GND` (intersection area 61.15 pt^2)
- 2. p1: `GND` overlaps `GND` (intersection area 61.15 pt^2)
- 3. p1: `GND` overlaps `GND` (intersection area 61.15 pt^2)
- 4. p1: `GND` overlaps `GND` (intersection area 61.15 pt^2)
- 5. p1: `GND` overlaps `GND` (intersection area 61.15 pt^2)
- 6. p1: `GND` overlaps `GND` (intersection area 61.15 pt^2)
- 7. p1: `GND` overlaps `GND` (intersection area 61.15 pt^2)
- 8. p1: `GND` overlaps `GND` (intersection area 61.15 pt^2)
- 9. p1: `5` overlaps `6` (intersection area 19.11 pt^2)
- 10. p1: `5` overlaps `7` (intersection area 19.11 pt^2)
- 11. p1: `5` overlaps `8` (intersection area 19.11 pt^2)
- 12. p1: `5` overlaps `9` (intersection area 19.11 pt^2)
- 13. p1: `5` overlaps `10` (intersection area 19.11 pt^2)
- 14. p1: `5` overlaps `11` (intersection area 19.11 pt^2)
- 15. p1: `5` overlaps `12` (intersection area 19.11 pt^2)
- 16. p1: `5` overlaps `13` (intersection area 19.11 pt^2)
- 17. p1: `GND` overlaps `GND` (intersection area 61.15 pt^2)
- 18. p1: `GND` overlaps `GND` (intersection area 61.15 pt^2)
- 19. p1: `GND` overlaps `GND` (intersection area 61.15 pt^2)
- 20. p1: `GND` overlaps `GND` (intersection area 61.15 pt^2)
- 21. p1: `GND` overlaps `GND` (intersection area 61.15 pt^2)
- 22. p1: `GND` overlaps `GND` (intersection area 61.15 pt^2)
- 23. p1: `GND` overlaps `GND` (intersection area 61.15 pt^2)
- 24. p1: `6` overlaps `7` (intersection area 19.11 pt^2)
- 25. p1: `6` overlaps `8` (intersection area 19.11 pt^2)
- 26. p1: `6` overlaps `9` (intersection area 19.11 pt^2)
- 27. p1: `6` overlaps `10` (intersection area 19.11 pt^2)
- 28. p1: `6` overlaps `11` (intersection area 19.11 pt^2)
- 29. p1: `6` overlaps `12` (intersection area 19.11 pt^2)
- 30. p1: `6` overlaps `13` (intersection area 19.11 pt^2)
- 31. p1: `GND` overlaps `GND` (intersection area 61.15 pt^2)
- 32. p1: `GND` overlaps `GND` (intersection area 61.15 pt^2)
- 33. p1: `GND` overlaps `GND` (intersection area 61.15 pt^2)
- 34. p1: `GND` overlaps `GND` (intersection area 61.15 pt^2)
- 35. p1: `GND` overlaps `GND` (intersection area 61.15 pt^2)
- 36. p1: `GND` overlaps `GND` (intersection area 61.15 pt^2)
- 37. p1: `7` overlaps `8` (intersection area 19.11 pt^2)
- 38. p1: `7` overlaps `9` (intersection area 19.11 pt^2)
- 39. p1: `7` overlaps `10` (intersection area 19.11 pt^2)
- 40. p1: `7` overlaps `11` (intersection area 19.11 pt^2)
- 41. p1: `7` overlaps `12` (intersection area 19.11 pt^2)
- 42. p1: `7` overlaps `13` (intersection area 19.11 pt^2)
- 43. p1: `GND` overlaps `GND` (intersection area 61.15 pt^2)
- 44. p1: `GND` overlaps `GND` (intersection area 61.15 pt^2)
- 45. p1: `GND` overlaps `GND` (intersection area 61.15 pt^2)
- 46. p1: `GND` overlaps `GND` (intersection area 61.15 pt^2)
- 47. p1: `GND` overlaps `GND` (intersection area 61.15 pt^2)
- 48. p1: `8` overlaps `9` (intersection area 19.11 pt^2)
- 49. p1: `8` overlaps `10` (intersection area 19.11 pt^2)
- 50. p1: `8` overlaps `11` (intersection area 19.11 pt^2)
- ... plus 156 additional pairs.

### Display schematic text-overlap findings
- Detected 84 overlapping word-box pairs.
- 1. p1: `PSRAM` overlaps `MOD1` (intersection area 3.49 pt^2)
- 2. p1: `GND` overlaps `GND` (intersection area 61.15 pt^2)
- 3. p1: `GND` overlaps `GND` (intersection area 61.15 pt^2)
- 4. p1: `1` overlaps `40` (intersection area 19.11 pt^2)
- 5. p1: `1` overlaps `41` (intersection area 19.11 pt^2)
- 6. p1: `GND` overlaps `GND` (intersection area 61.15 pt^2)
- 7. p1: `40` overlaps `41` (intersection area 38.21 pt^2)
- 8. p1: `ESP32-S3-WROOM-1-N16R8` overlaps `GND` (intersection area 15.18 pt^2)
- 9. p1: `2` overlaps `RS485_B` (intersection area 3.09 pt^2)
- 10. p1: `A1` overlaps `1A2` (intersection area 4.81 pt^2)
- 11. p1: `A1` overlaps `2` (intersection area 1.63 pt^2)
- 12. p1: `A1` overlaps `TVS2` (intersection area 5.21 pt^2)
- 13. p1: `A1` overlaps `SMAJ12CA` (intersection area 9.41 pt^2)
- 14. p1: `1A2` overlaps `SMAJ12CA` (intersection area 5.64 pt^2)
- 15. p1: `2` overlaps `TVS2` (intersection area 14.21 pt^2)
- 16. p1: `SMAJ12CA` overlaps `RS485_B` (intersection area 2.29 pt^2)
- 17. p1: `13` overlaps `EPD_FFC_24` (intersection area 0.52 pt^2)
- 18. p1: `2` overlaps `BTN2_IN` (intersection area 1.59 pt^2)
- 19. p1: `2` overlaps `BTN1_IN` (intersection area 1.59 pt^2)
- 20. p1: `2` overlaps `BTN3_IN` (intersection area 1.59 pt^2)
- 21. p1: `1` overlaps `BTN3_IN` (intersection area 5.22 pt^2)
- 22. p1: `1` overlaps `BTN2_IN` (intersection area 5.22 pt^2)
- 23. p1: `1` overlaps `1` (intersection area 19.11 pt^2)
- 24. p1: `2` overlaps `2` (intersection area 19.11 pt^2)
- 25. p1: `C7` overlaps `C7` (intersection area 24.29 pt^2)
- 26. p1: `100nF` overlaps `100nF` (intersection area 57.45 pt^2)
- 27. p1: `RO` overlaps `UART_RX_3V3` (intersection area 4.43 pt^2)
- 28. p1: `RO` overlaps `RO` (intersection area 41.08 pt^2)
- 29. p1: `1` overlaps `UART_RX_3V3` (intersection area 6.91 pt^2)
- 30. p1: `1` overlaps `1` (intersection area 19.11 pt^2)
- 31. p1: `RE` overlaps `RE` (intersection area 38.21 pt^2)
- 32. p1: `2` overlaps `DE_RE` (intersection area 1.01 pt^2)
- 33. p1: `2` overlaps `UART_RX_3V3` (intersection area 2.56 pt^2)
- 34. p1: `2` overlaps `2` (intersection area 19.11 pt^2)
- 35. p1: `DE` overlaps `DE` (intersection area 38.21 pt^2)
- 36. p1: `3` overlaps `DE_RE` (intersection area 0.37 pt^2)
- 37. p1: `3` overlaps `3` (intersection area 19.11 pt^2)
- 38. p1: `DI` overlaps `UART_TX_3V3` (intersection area 2.94 pt^2)
- 39. p1: `DI` overlaps `DI` (intersection area 29.62 pt^2)
- 40. p1: `4` overlaps `UART_TX_3V3` (intersection area 6.91 pt^2)
- 41. p1: `4` overlaps `4` (intersection area 19.11 pt^2)
- 42. p1: `GND` overlaps `GND` (intersection area 61.15 pt^2)
- 43. p1: `5` overlaps `GND` (intersection area 3.92 pt^2)
- 44. p1: `5` overlaps `5` (intersection area 19.11 pt^2)
- 45. p1: `A` overlaps `A` (intersection area 17.20 pt^2)
- 46. p1: `6` overlaps `GND` (intersection area 0.20 pt^2)
- 47. p1: `6` overlaps `6` (intersection area 19.11 pt^2)
- 48. p1: `B` overlaps `B` (intersection area 20.07 pt^2)
- 49. p1: `7` overlaps `7` (intersection area 19.11 pt^2)
- 50. p1: `VCC` overlaps `VCC` (intersection area 57.34 pt^2)
- ... plus 34 additional pairs.

## Reviewer Notes
- This tool detects text-text overlaps via PDF word bounding boxes. Manual visual review is still required for symbol/wire/text readability.
- Use the generated crops as the codex-owned evidence set in the active CP packet.
