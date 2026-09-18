const CALLSIGNS = {
  AA: 'American', AAL: 'American',
  AC: 'Air Canada', ACA: 'Air Canada',
  AF: 'Air France', AFR: 'Air France',
  AI: 'Air India', AIC: 'Air India',
  AY: 'Finnair', FIN: 'Finnair',
  AZ: 'Alitalia', AZA: 'Alitalia',
  BA: 'Speedbird', BAW: 'Speedbird',
  CA: 'Air China', CCA: 'Air China',
  CI: 'China Airlines', CAL: 'China Airlines',
  CX: 'Cathay Pacific', CPA: 'Cathay Pacific',
  CZ: 'China Southern', CSN: 'China Southern',
  DL: 'Delta', DAL: 'Delta',
  DY: 'Norwegian', NAX: 'Norwegian',
  EI: 'Shamrock', EIN: 'Shamrock',
  EK: 'Emirates', UAE: 'Emirates',
  ET: 'Ethiopian', ETH: 'Ethiopian',
  EY: 'Etihad', ETD: 'Etihad',
  EZY: 'Easy', U2: 'Easy', EJU: 'Easy',
  FI: 'Icelandair', ICE: 'Icelandair',
  FR: 'Ryanair', RYR: 'Ryanair',
  HU: 'Hainan', CHH: 'Hainan',
  HV: 'Transavia', TRA: 'Transavia',
  IB: 'Iberia', IBE: 'Iberia',
  JL: 'Japan Air', JAL: 'Japan Air',
  KE: 'Korean Air', KAL: 'Korean Air',
  KL: 'KLM', KLM: 'KLM',
  LH: 'Lufthansa', DLH: 'Lufthansa',
  LO: 'LOT', LOT: 'LOT',
  LS: 'Channex', EXS: 'Channex',
  LX: 'Swiss', SWR: 'Swiss',
  MS: 'Egyptair', MSR: 'Egyptair',
  MU: 'China Eastern', CES: 'China Eastern',
  NH: 'All Nippon', ANA: 'All Nippon',
  NZ: 'New Zealand', ANZ: 'New Zealand',
  OS: 'Austrian', AUA: 'Austrian',
  OU: 'Croatia', CTN: 'Croatia',
  QF: 'Qantas', QFA: 'Qantas',
  QR: 'Qatar', QTR: 'Qatar',
  SA: 'Springbok', SAA: 'Springbok',
  SK: 'Scandinavian', SAS: 'Scandinavian',
  SN: 'Bee-Line', BEL: 'Bee-Line',
  SQ: 'Singapore', SIA: 'Singapore',
  SU: 'Aeroflot', AFL: 'Aeroflot',
  SV: 'Saudia', SVA: 'Saudia',
  TFL: 'Orange', TOM: 'TomJet', TUI: 'TuiJet', TBH: 'Belgian',
  TK: 'Turkish', THY: 'Turkish',
  TP: 'TAP Air', TAP: 'TAP Air',
  TS: 'Air Transat', TSC: 'Air Transat',
  UA: 'United', UAL: 'United',
  VS: 'Virgin Atlantic', VIR: 'Virgin Atlantic',
  W6: 'Wizz Air', WZZ: 'Wizz Air',
  WN: 'Southwest', SWA: 'Southwest',
  WS: 'WestJet', WJA: 'WestJet'
};

export function callsignName(callsign, route) {
  if (route) {
    if (route.airline_iata && CALLSIGNS[route.airline_iata]) return CALLSIGNS[route.airline_iata];
    if (route.airline_icao && CALLSIGNS[route.airline_icao]) return CALLSIGNS[route.airline_icao];
  }
  if (!callsign) return '';
  const m = String(callsign).toUpperCase().match(/^([A-Z]{2,3})/);
  if (!m) return '';
  if (CALLSIGNS[m[1]]) return CALLSIGNS[m[1]];
  if (m[1].length === 3 && CALLSIGNS[m[1].slice(0, 2)]) return CALLSIGNS[m[1].slice(0, 2)];
  return '';
}