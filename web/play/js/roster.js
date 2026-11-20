// The six original teams (mirrors Source/HeatCheck/Private/HCRoster.cpp).
export const Hair = { None: 0, Buzz: 1, Flattop: 2, Afro: 3, Braids: 4, Mohawk: 5, Curls: 6, Bun: 7 };
export const HairMesh = [null, 'SK_Hair_Buzz', 'SK_Hair_Flattop', 'SK_Hair_Afro', 'SK_Hair_Braids', 'SK_Hair_Mohawk', 'SK_Hair_Curls', 'SK_Hair_Bun'];
export const Beard = { None: 0, Full: 1, Goatee: 2 };

function P(first, last, nick, number, spd, sht, thr, dnk, pas, pow, stl, blk, clu, skin, hair, hairColor, beard, headband, wristbands, height, build) {
  return {
    first, last, nick, number,
    speed: spd, shoot: sht, three: thr, dunk: dnk, pass: pas, power: pow, steal: stl, block: blk, clutch: clu,
    skin: '#' + skin, hair, hairColor: '#' + hairColor, beard, headband, wristbands, height, build,
  };
}

function T(city, name, abbr, primary, secondary, accent, players) {
  return { city, name, abbr, primary: '#' + primary, secondary: '#' + secondary, accent: '#' + accent, players };
}

export const TEAMS = [
  T('Neon City', 'Voltage', 'NEO', 'FFD60A', '111111', '00E5FF', [
    P('Dash', 'Mercer', 'Live Wire', 3, 9, 7, 8, 6, 8, 4, 8, 3, 7, '5C3A21', Hair.Flattop, '15100C', Beard.None, true, true, 0.97, 0.97),
    P('Tremont', 'Baxley', 'Tank', 34, 5, 6, 3, 9, 5, 9, 4, 8, 6, '7A4B2A', Hair.Buzz, '15100C', Beard.Full, false, false, 1.05, 1.10),
  ]),
  T('Bay Harbor', 'Krakens', 'BAY', '0B7A75', 'FF6B1A', 'F2F2F2', [
    P('Rio', 'Castellanos', 'Splash', 11, 8, 8, 9, 5, 7, 4, 6, 3, 8, 'C68642', Hair.Curls, '1A1410', Beard.None, false, true, 0.97, 0.96),
    P('Gus', 'Halvorsen', 'The Anchor', 50, 4, 6, 2, 8, 6, 10, 3, 9, 5, 'F1C27D', Hair.Bun, '8A5A2B', Beard.Goatee, false, false, 1.07, 1.12),
  ]),
  T('Red Rock', 'Scorpions', 'RRK', 'B3122E', 'E9C46A', '1B1B1B', [
    P('Marquis', 'Delacroix', 'Sting', 7, 8, 7, 7, 8, 6, 6, 7, 5, 7, '4A2C1A', Hair.Braids, '120D0A', Beard.None, false, true, 1.0, 1.0),
    P('Javier', 'Montalvo', 'Desert Storm', 21, 6, 8, 6, 6, 7, 7, 5, 6, 9, 'B5794A', Hair.Mohawk, '1A1410', Beard.Goatee, true, false, 1.02, 1.03),
  ]),
  T('Frostburg', 'Yetis', 'FRB', 'A9D6F5', '0E2A47', 'FFFFFF', [
    P('Nils', 'Brekke', 'Avalanche', 15, 6, 7, 7, 7, 6, 8, 5, 7, 6, 'F3D1B5', Hair.Buzz, 'C9A36B', Beard.Full, false, false, 1.04, 1.06),
    P('Kenji', 'Arakawa', 'Flurry', 4, 10, 7, 8, 4, 9, 3, 9, 2, 7, 'E8B98F', Hair.Mohawk, '0F0C0A', Beard.None, true, true, 0.95, 0.94),
  ]),
  T('Steel Valley', 'Forge', 'STV', '5A6270', 'FF8C1A', 'FFD166', [
    P('Hank', 'Kowalski', 'Hammer', 24, 5, 6, 4, 9, 5, 10, 4, 8, 6, 'E0AC69', Hair.Flattop, '7A2E10', Beard.None, false, true, 1.06, 1.12),
    P('Andre', 'Whitfield', 'Spark Plug', 9, 9, 8, 7, 7, 7, 5, 8, 4, 7, '6B4226', Hair.Afro, '120D0A', Beard.None, true, false, 0.98, 0.98),
  ]),
  T('Sunset Coast', 'Surge', 'SSC', 'FF4F79', '2B2D9B', '2EC4B6', [
    P('Malik', 'Fontaine', 'Riptide', 1, 9, 7, 8, 9, 6, 5, 7, 5, 8, '3D2616', Hair.Afro, '0D0907', Beard.Goatee, false, true, 1.0, 1.0),
    P('Theo', 'Lindqvist', 'Breaker', 33, 5, 6, 3, 8, 6, 9, 4, 9, 5, 'F1C27D', Hair.Curls, '5A3A1E', Beard.Full, true, false, 1.06, 1.10),
  ]),
];
