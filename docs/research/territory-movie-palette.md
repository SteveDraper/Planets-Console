# Prefix-separated palette for the Territory movie

Research for [issue #602](https://github.com/SteveDraper/Planets-Console/issues/602). Map: [issue #597](https://github.com/SteveDraper/Planets-Console/issues/597).

## Answer

Bake one ordered list of 8-bit sRGB colors. Index 0 is the first owner added in a selection, index 1 the next new owner, and so on. Player selections and league-team selections keep separate indexes and both read this list.

**Separation metric.** CIEDE2000 colour difference, written ΔE00, with parametric factors kL = kC = kH = 1. The normative definition is [ISO/CIE 11664-6:2022](https://www.iso.org/standard/82662.html). It takes CIELAB L*, a*, b* coordinates calculated under [ISO/CIE 11664-4:2019](https://www.iso.org/standard/74166.html). The factors of 1 are the formula's reference parametric weights. Sharma, Wu, and Dalal (2005) use the same weights.

**Prefix separation.** For a prefix length n ≥ 2, S(n) is the minimum ΔE00 between any two of the first n colors (indexes 0 through n - 1).

**Order rule.**

1. Indexes 0 and 1 are a mutually farthest pair on the 8-bit sRGB cube. Each is an exhaustive maximizer of ΔE00 against the other over all 256^3 triples. Index 0 is the member with the greater CIELAB L*. An equal L* would take the lexicographically smaller (R, G, B) as index 0. That tie did not occur.
2. Each later index is the unused triple that maximizes the minimum ΔE00 to the colors already chosen. This is the sequential rule in Glasbey, van der Heijden, Toh, and Gray (2007), equation (3), with their distance D replaced by ΔE00. A tie takes the lexicographically smallest (R, G, B).
3. Past index 31, keep applying rule 2 on the same cube. Earlier indexes stay fixed.

On this list S(n) falls at every step, and S(n) equals the ΔE00 from index n - 1 to its nearest earlier index. A full game of 11 owners uses indexes 0 through 10, where S(11) = 32.1889. The baked list runs through index 31, where S(32) = 19.3809.

Baked order:

`#8fff00`, `#00006e`, `#ffc0ff`, `#1f3c00`, `#bd2d00`, `#00dcff`, `#ffae00`, `#3974fd`, `#d0008e`, `#809276`, `#290e00`, `#fffcef`, `#005a65`, `#ff927e`, `#826000`, `#8e8593`, `#00ffd2`, `#4b475d`, `#001313`, `#7800f4`, `#a7c1ff`, `#a9ac00`, `#c66aff`, `#88032e`, `#007f00`, `#00959e`, `#af8e69`, `#00be57`, `#fd0050`, `#5f5e53`, `#da7ca1`, `#fff48f`

## Why this order

Adding an owner has to leave earlier owners on their colors. A single nested list is the order that does that while making every leading prefix as separated as the rule allows: rule 1 maximizes S(2), and rule 2 then maximizes S(n + 1) given the first n colors.

Glasbey et al. also solved a fixed-size version with simulated annealing. Under their Euclidean CIELAB distance, that search raised the minimum for a set of 11 above the nested prefix (their D = 74 against D = 67). A fixed-size set with a higher minimum assigns different colors when the selection count changes. The nested rule is the one this movie can bake.

Their published colours are a different list. Equation (2) in that paper is Euclidean distance in CIELAB after a Bradford adaptation from sRGB's D65 white to D50, and their sequential search starts at white. The metric here is ΔE00 in CIELAB with the sRGB D65 white and no chromatic adaptation. That is the input ISO/CIE 11664-6 takes from ISO/CIE 11664-4 when the stimulus white is D65.

The search scores distances among palette colors. A background color is not one of the chosen colors. The sphere-map background is still open on the map, so it was left out of the objective. The early indexes that buy the large S(n) include dark fills: index 1 is L* 10.00 (`#00006e`), index 3 is L* 22.03 (`#1f3c00`), and index 10 is L* 7.10 (`#290e00`). Index 11, the first color past a full roster of 11, is near white (`#fffcef`, L* 98.87).

## Method

### Coordinates

Encoding is 8-bit sRGB as specified by IEC 61966-2-1:1999. The transfer function used here is the one published for that encoding in [CSS Color Module Level 4, section 10.2](https://www.w3.org/TR/css-color-4/#predefined-sRGB): for a channel C in 0..1,

- if C ≤ 0.04045, linear = C / 12.92
- otherwise linear = ((C + 0.055) / 1.055)^2.4

Chromaticities are Table 0.2 of Stokes, Anderson, Chandrasekar, and Motta, [A Standard Default Color Space for the Internet - sRGB](https://www.w3.org/Graphics/Color/sRGB.html) (x, y):

| | x | y |
| --- | --- | --- |
| Red | 0.6400 | 0.3300 |
| Green | 0.3000 | 0.6000 |
| Blue | 0.1500 | 0.0600 |
| D65 | 0.3127 | 0.3290 |

Table 0.1 on that page gives D65 y = 0.3291. The matrix below uses Table 0.2, which is the table of primaries and the illuminant for the transform. White XYZ is (x/y, 1, (1 - x - y)/y) = (0.9504559270516716, 1, 1.0890577507598784).

The linear-sRGB to XYZ matrix is the unique matrix whose columns are the primary XYZ vectors and whose action on (1, 1, 1) is that white:

| | R | G | B |
| --- | --- | --- | --- |
| X | 0.41239079926595934 | 0.357584339383878 | 0.1804807884018343 |
| Y | 0.21263900587151027 | 0.715168678767756 | 0.07219231536073371 |
| Z | 0.01933081871559182 | 0.11919477979462598 | 0.9505321522496607 |

This matches the sample `lin_sRGB_to_XYZ` matrix in CSS Color Module Level 4 (`conversions.js` in the CSSWG draft) to within 2 × 10^-16. That sample is marked non-normative there; it is a cross-check, and the spec's comment on it says the conversion uses sRGB's own D65 white with no chromatic adaptation.

CIELAB uses the ISO/CIE 11664-4:2019 formula with that white (Xn, Yn, Zn), and the standard's exact constants ε = (6/29)^3 = 216/24389 and κ = (29/3)^3 = 24389/27:

- f(t) = t^(1/3) when t > ε, otherwise f(t) = (κ t + 16) / 116
- L* = 116 f(Y/Yn) - 16
- a* = 500 (f(X/Xn) - f(Y/Yn))
- b* = 200 (f(Y/Yn) - f(Z/Zn))

sRGB (255, 255, 255) converts to L* = 100, a* = 0, b* = 0. sRGB (0, 0, 0) converts to L* = 0, a* = 0, b* = 0.

ISO/CIE 11664-6 applies to stimuli perceived as reflecting or transmitting objects, including displays used to simulate those objects when the tristimulus values are normalized. It does not apply to stimuli that appear as primary light sources. These fills are treated as surface colors in sRGB.

### ΔE00 check

The implementation is a NumPy port of Sharma, Wu, and Dalal's `deltaE2000.m` (kL = kC = kH = 1). Against their 34 published pairs in [`ciede2000testdata.txt`](https://hajim.rochester.edu/ece/sites/gsharma/ciede2000/dataNprograms/ciede2000testdata.txt), the maximum absolute error is 4.95 × 10^-5. Swapping the two colours of each pair changes no result at float64 precision. Reported ΔE00 values below are those float64 results printed to 4 decimal places. The fourth decimal sits at that verification floor.

### Search

Candidates are every 8-bit triple, visited in lexicographic (R, G, B) order so a tie takes the smallest triple.

The opening pair was found in two stages:

1. All pairs on the lattice whose channels lie in {0, 8, 16, ..., 248, 255} (33^3 = 35937 colors).
2. The top 20 lattice pairs, each refined by alternating exhaustive farthest-point search on the full cube until both ends were stable.

Every one of those 20 lattice pairs refined into the same chartreuse/dark-blue basin or a neighbor of it. The retained pair has ΔE00 = 119.4740:

- index 0: (143, 255, 0), `#8fff00`, L* = 90.49
- index 1: (0, 0, 110), `#00006e`, L* = 10.00

Each end is the lex-first maximizer of ΔE00 from the other on the full cube. The next distinct refined pair, (5, 0, 110) with (141, 255, 0), has ΔE00 = 119.3149.

Indexes 2 through 31 were then chosen one at a time by rule 2, each by an exhaustive scan of the cube with the colors already chosen blocked.

## Baked colors

S(n) is the prefix separation after this index is included (n = index + 1). "Nearest" is the earlier index at that ΔE00. L*, a*, b* are rounded to 2 decimal places from the conversion above. Bake the hex bytes.

| Index | Hex | sRGB | L* | a* | b* | Nearest | S(n) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | `#8fff00` | 143, 255, 0 | 90.49 | -63.36 | 86.53 | - | - |
| 1 | `#00006e` | 0, 0, 110 | 10.00 | 42.63 | -58.05 | 0 | 119.4740 |
| 2 | `#ffc0ff` | 255, 192, 255 | 85.09 | 32.67 | -22.20 | 1 | 75.1785 |
| 3 | `#1f3c00` | 31, 60, 0 | 22.03 | -21.83 | 29.90 | 1 | 65.5845 |
| 4 | `#bd2d00` | 189, 45, 0 | 42.30 | 55.33 | 54.86 | 3 | 50.3849 |
| 5 | `#00dcff` | 0, 220, 255 | 80.96 | -32.21 | -29.51 | 2 | 49.0493 |
| 6 | `#ffae00` | 255, 174, 0 | 77.00 | 19.23 | 80.32 | 4 | 39.7658 |
| 7 | `#3974fd` | 57, 116, 253 | 52.34 | 28.57 | -73.62 | 5 | 36.0192 |
| 8 | `#d0008e` | 208, 0, 142 | 46.13 | 75.98 | -18.41 | 4 | 34.6072 |
| 9 | `#809276` | 128, 146, 118 | 58.47 | -11.90 | 12.73 | 0 | 33.4103 |
| 10 | `#290e00` | 41, 14, 0 | 7.10 | 12.56 | 10.87 | 1 | 32.1889 |
| 11 | `#fffcef` | 255, 252, 239 | 98.87 | -1.21 | 6.57 | 5 | 29.3930 |
| 12 | `#005a65` | 0, 90, 101 | 34.50 | -18.54 | -12.87 | 3 | 29.0997 |
| 13 | `#ff927e` | 255, 146, 126 | 71.78 | 39.03 | 28.57 | 6 | 28.5923 |
| 14 | `#826000` | 130, 96, 0 | 42.93 | 6.14 | 50.42 | 4 | 27.0291 |
| 15 | `#8e8593` | 142, 133, 147 | 56.72 | 6.11 | -6.27 | 8 | 26.9054 |
| 16 | `#00ffd2` | 0, 255, 210 | 89.94 | -60.15 | 7.48 | 0 | 25.3711 |
| 17 | `#4b475d` | 75, 71, 93 | 31.33 | 6.87 | -12.35 | 15 | 24.0896 |
| 18 | `#001313` | 0, 19, 19 | 4.63 | -5.61 | -1.98 | 1 | 23.1991 |
| 19 | `#7800f4` | 120, 0, 244 | 38.77 | 80.28 | -90.69 | 8 | 22.9123 |
| 20 | `#a7c1ff` | 167, 193, 255 | 78.21 | 5.59 | -33.34 | 5 | 22.5763 |
| 21 | `#a9ac00` | 169, 172, 0 | 67.98 | -17.37 | 70.04 | 9 | 22.4127 |
| 22 | `#c66aff` | 198, 106, 255 | 61.25 | 60.98 | -59.81 | 2 | 22.2250 |
| 23 | `#88032e` | 136, 3, 46 | 28.11 | 51.15 | 15.09 | 10 | 22.0619 |
| 24 | `#007f00` | 0, 127, 0 | 45.88 | -51.41 | 49.62 | 9 | 21.9070 |
| 25 | `#00959e` | 0, 149, 158 | 56.05 | -29.30 | -14.17 | 5 | 20.9970 |
| 26 | `#af8e69` | 175, 142, 105 | 61.20 | 7.29 | 24.42 | 13 | 20.6933 |
| 27 | `#00be57` | 0, 190, 87 | 67.66 | -62.55 | 40.51 | 0 | 20.6239 |
| 28 | `#fd0050` | 253, 0, 80 | 53.46 | 81.33 | 30.98 | 8 | 20.5318 |
| 29 | `#5f5e53` | 95, 94, 83 | 39.69 | -1.78 | 6.46 | 12 | 20.3295 |
| 30 | `#da7ca1` | 218, 124, 161 | 63.26 | 40.88 | -3.70 | 2 | 19.3990 |
| 31 | `#fff48f` | 255, 244, 143 | 95.14 | -9.83 | 49.80 | 11 | 19.3809 |

## Console per-player palette

`PLAYER_COLOR_PRESET` in `packages/frontend/src/lib/playerColor.ts` is 16 hex colors addressed by `playerId % 16`. In that listed order it does not have the prefix property.

Under the same ΔE00:

- S(2) = 56.3446 and S(11) = 7.9049 along the listed order.
- The farthest cube color from the first preset entry `#38bdf8` is `#35001b` at ΔE00 = 73.8077. The second preset entry `#f472b6` lies at ΔE00 = 56.3446 from the first, so the listed order fails rule 2 at the second color.
- Reordering these 16 colors alone by rule 2, starting from the first entry, yields preset indexes 0, 13, 7, 14, 4, 8, 10, 1, 9, 12, 6, 3, 5, 11, 15, 2. That is not the listed order.

The movie list above is a separate ordered palette.

## Left open

What happens to an index when an owner is unchecked is [issue #600](https://github.com/SteveDraper/Planets-Console/issues/600). This note does not specify reuse, retirement, or a gap.

## Sources

- ISO/CIE 11664-6:2022. *Colorimetry - Part 6: CIEDE2000 colour-difference formula.* Confirmed text is based on CIE 142-2001. https://www.iso.org/standard/82662.html
- ISO/CIE 11664-4:2019. *Colorimetry - Part 4: CIE 1976 L\*a\*b\* colour space.* Confirmed 2024. https://www.iso.org/standard/74166.html
- IEC 61966-2-1:1999. *Multimedia systems and equipment - Colour measurement and management - Part 2-1: Colour management - Default RGB colour space - sRGB.*
- Stokes, M., Anderson, M., Chandrasekar, S., and Motta, R. *A Standard Default Color Space for the Internet - sRGB.* Table 0.2. https://www.w3.org/Graphics/Color/sRGB.html
- World Wide Web Consortium. *CSS Color Module Level 4.* Section 10.2 (sRGB transfer function) and the sample `lin_sRGB_to_XYZ` matrix. https://www.w3.org/TR/css-color-4/
- Sharma, G., Wu, W., and Dalal, E. N. (2005). The CIEDE2000 color-difference formula: Implementation notes, supplementary test data, and mathematical observations. *Color Research and Application,* 30(1), 21-30. https://doi.org/10.1002/col.20070 . PDF: https://hajim.rochester.edu/ece/sites/gsharma/ciede2000/ciede2000noteCRNA.pdf . Test pairs: https://hajim.rochester.edu/ece/sites/gsharma/ciede2000/dataNprograms/ciede2000testdata.txt . Implementation ported from https://hajim.rochester.edu/ece/sites/gsharma/ciede2000/dataNprograms/deltaE2000.m
- Glasbey, C., van der Heijden, G., Toh, V. F. K., and Gray, A. (2007). Colour displays for categorical images. *Color Research and Application,* 32(4), 304-309. https://doi.org/10.1002/col.20327 . Author manuscript: https://strathprints.strath.ac.uk/30312/1/colorpaper_2006.pdf
