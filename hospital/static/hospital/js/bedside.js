/* Bedside scene: an animated picture of the inpatient and everything attached to them, drawn from the values entered.
   - IV: drops fall in the drip chamber at exactly rate × drop factor ÷ 60 per minute; the bag level is remaining ÷ bag size
     and goes down in real time at the set rate.
   - Monitor: ECG and pulse-oximeter waves at the entered heart rate, breathing trace and chest movement at the
     respiratory rate, numbers and alarms from the last observations (NEWS2 parameters scoring 2–3 turn amber/red).
   - Oxygen: the flowmeter float sits at the set flow, bubbles in the humidifier come faster with more flow.
   - Catheter: urine drips into the bag at the hourly output; the bag fills to the recorded volume.
   - Head of bed at the set angle; collar, traction weight, chest drain bubbling, NG feed, BP cuff cycle.
   MFBedside.derive and MFBedside.news2 mirror hospital/bedside.py. Teaching/documentation picture, not a monitor. */
(() => {
  'use strict';
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const rnd = (x, d = 0) => { const m = 10 ** d; return Math.floor(x * m + 0.5) / m; };
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const NS = 'http://www.w3.org/2000/svg';

  /* ------------------------------------------------------------------ maths (mirror of bedside.py) */
  function fio2(o2) {
    if (!o2.on) return 21;
    const d = o2.device, f = o2.flow_l_min;
    if (d === 'nasal') return Math.min(44, rnd(21 + 4 * f));
    if (d === 'mask') return Math.min(60, rnd(35 + (f - 5) * 5));
    if (d === 'nrb') return Math.min(90, rnd(60 + (f - 10) * 5));
    return o2.fio2 ?? 40;
  }
  function derive(dev, weight) {
    const iv = dev.iv, cath = dev.catheter, rate = iv.rate_ml_h, df = iv.drop_factor;
    const dpm = iv.on ? rnd(rate * df / 60, 1) : 0;
    const hoursLeft = iv.on && rate > 0 ? rnd(iv.remaining_ml / rate, 1) : null;
    const w = weight && weight > 0 ? weight : null;
    const uo = cath.on && w ? rnd(cath.output_ml_h / w, 2) : null;
    const warnings = [];
    if (iv.on && rate === 0) warnings.push('IV is up but the rate is 0 mL/h.');
    if (iv.on && iv.remaining_ml < 50) warnings.push(`IV bag nearly empty (${iv.remaining_ml} mL left).`);
    else if (hoursLeft != null && hoursLeft < 1) warnings.push(`IV bag runs out in about ${rnd(hoursLeft * 60)} minutes.`);
    if (iv.on && !iv.pump && dpm > 100) warnings.push(`${dpm} drops/min is too fast to count by gravity: use an infusion pump.`);
    if (uo != null && uo < .5) warnings.push(`Urine output ${uo} mL/kg/h is below 0.5: check fluids and the catheter.`);
    if (cath.on && cath.bag_ml >= 1500) warnings.push('Urine bag is nearly full: empty and record.');
    if (dev.chest_drain.on && dev.chest_drain.bubbling) warnings.push('Chest drain is bubbling: air leak from the lung. Do not clamp.');
    return {drops_per_min: dpm, hours_left: hoursLeft, fio2: fio2(dev.oxygen), urine_ml_kg_h: uo, warnings};
  }
  const band = (v, bands) => { for (const [lim, s] of bands) if (v <= lim) return s; return bands.at(-1)[1]; };
  function news2(o) {
    const parts = {}, missing = [];
    const has = k => o[k] != null && o[k] !== '';
    if (has('resp_rate')) parts.resp_rate = band(+o.resp_rate, [[8, 3], [11, 1], [20, 0], [24, 2], [999, 3]]); else missing.push('resp_rate');
    if (has('spo2')) parts.spo2 = band(+o.spo2, [[91, 3], [93, 2], [95, 1], [100, 0]]); else missing.push('spo2');
    parts.oxygen = o.on_oxygen ? 2 : 0;
    if (has('systolic')) parts.systolic = band(+o.systolic, [[90, 3], [100, 2], [110, 1], [219, 0], [999, 3]]); else missing.push('systolic');
    if (has('heart_rate')) parts.heart_rate = band(+o.heart_rate, [[40, 3], [50, 1], [90, 0], [110, 1], [130, 2], [999, 3]]); else missing.push('heart_rate');
    parts.consciousness = (o.consciousness || 'A') === 'A' ? 0 : 3;
    if (has('temperature_c')) parts.temperature_c = band(+o.temperature_c, [[35, 3], [36, 1], [38, 0], [39, 1], [99, 2]]); else missing.push('temperature_c');
    if (missing.length === 5) return null;
    const total = Object.values(parts).reduce((a, b) => a + b, 0);
    const risk = total >= 7 ? 'high' : total >= 5 ? 'medium' : Object.values(parts).includes(3) ? 'low-medium' : 'low';
    return {total, parts, risk, missing};
  }

  /* ------------------------------------------------------------------ waveforms */
  // One heartbeat (0..1) as a P-QRS-T shape; returns -1..1 (up is positive).
  function ecg(ph) {
    const g = (c, w, a) => a * Math.exp(-((ph - c) ** 2) / (2 * w * w));
    return g(.12, .025, .12) - g(.235, .008, .14) + g(.25, .009, 1) - g(.268, .01, .25) + g(.45, .045, .28);
  }
  const pleth = ph => { const p = (ph + .82) % 1; return Math.exp(-((p - .18) ** 2) / .006) * .9 + Math.exp(-((p - .42) ** 2) / .01) * .32; };

  /* ------------------------------------------------------------------ scene */
  const HINGE = [400, 345];
  const rot = ([x, y], deg) => { const a = deg * Math.PI / 180, dx = x - HINGE[0], dy = y - HINGE[1]; return [HINGE[0] + dx * Math.cos(a) - dy * Math.sin(a), HINGE[1] + dx * Math.sin(a) + dy * Math.cos(a)]; };

  function build(host) {
    host.innerHTML = `<svg viewBox="0 0 960 500" class="bs-scene" role="img" aria-labelledby="bs-title"><title id="bs-title">Patient in bed with attached equipment</title>
      <defs>
        <linearGradient id="bs-wall" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#EAF1EE"/><stop offset="1" stop-color="#DCE7E2"/></linearGradient>
        <linearGradient id="bs-fluid" x1="0" x2="1"><stop offset="0" stop-color="#CFEAF4"/><stop offset=".5" stop-color="#E9F7FB"/><stop offset="1" stop-color="#BFE2EF"/></linearGradient>
        <linearGradient id="bs-blood" x1="0" x2="1"><stop offset="0" stop-color="#8E1B27"/><stop offset=".5" stop-color="#B42634"/><stop offset="1" stop-color="#7E1621"/></linearGradient>
        <linearGradient id="bs-urine" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#F3D36A"/><stop offset="1" stop-color="#E2B33D"/></linearGradient>
        <linearGradient id="bs-blanket" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#8FC3D6"/><stop offset="1" stop-color="#5E9DB5"/></linearGradient>
        <linearGradient id="bs-skin" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="var(--bs-skin-1,#B9876A)"/><stop offset="1" stop-color="var(--bs-skin-2,#9A6A50)"/></linearGradient>
        <clipPath id="bs-bagclip"><path d="M84,66 h52 v86 q0,14 -14,18 h-24 q-14,-4 -14,-18z"/></clipPath>
        <clipPath id="bs-ubagclip"><path d="M540,392 h44 v52 q0,10 -10,12 h-24 q-10,-2 -10,-12z"/></clipPath>
        <clipPath id="bs-dclip"><rect x="452" y="414" width="44" height="52" rx="6"/></clipPath>
        <clipPath id="bs-screen"><rect x="622" y="44" width="300" height="168" rx="6"/></clipPath>
      </defs>
      <rect width="960" height="500" fill="url(#bs-wall)"/>
      <rect y="470" width="960" height="30" fill="#C9D6D0"/><path d="M0,470 H960" stroke="#B5C5BE" stroke-width="2"/>
      <rect x="168" y="40" width="96" height="40" rx="6" fill="#D3DED9" stroke="#B9C9C2"/><text x="216" y="65" class="bs-tiny" text-anchor="middle">O₂ · AIR · VAC</text>

      <!-- oxygen flowmeter and humidifier -->
      <g id="bs-o2" class="bs-hit" data-open="oxygen" tabindex="0" role="button" aria-label="Oxygen">
        <rect x="202" y="82" width="28" height="92" rx="6" fill="#F7FBFA" stroke="#9FB6AC"/>
        <rect x="210" y="88" width="12" height="70" rx="5" fill="#E8F3EF" stroke="#B9CBC3"/>
        ${[0, 5, 10, 15].map(v => `<path d="M223,${154 - v * 4.4} h5" stroke="#7D958B"/><text x="232" y="${157 - v * 4.4}" class="bs-tiny">${v}</text>`).join('')}
        <circle id="bs-o2ball" cx="216" cy="154" r="4.6" fill="#0F7B78"/>
        <rect x="204" y="178" width="24" height="40" rx="6" fill="#DCF0F5" stroke="#9FB6AC"/>
        <g id="bs-o2bub"></g>
        <text id="bs-o2txt" x="216" y="232" class="bs-lbl" text-anchor="middle"></text>
      </g>
      <path id="bs-o2tube" fill="none" stroke="#B9DCEA" stroke-width="4" stroke-linecap="round"/>

      <!-- IV pole, bag, drip chamber, pump -->
      <g id="bs-iv" class="bs-hit" data-open="iv" tabindex="0" role="button" aria-label="IV infusion">
        <path d="M110,30 V462 M78,462 H142" stroke="#8C9AA3" stroke-width="5" stroke-linecap="round"/><circle cx="80" cy="466" r="5" fill="#59656C"/><circle cx="140" cy="466" r="5" fill="#59656C"/>
        <path d="M90,40 H130 M110,40 v14" stroke="#8C9AA3" stroke-width="3" stroke-linecap="round"/>
        <path d="M84,66 h52 v86 q0,14 -14,18 h-24 q-14,-4 -14,-18z" fill="#F3FAFC" stroke="#9FB6C2" stroke-width="1.5"/>
        <rect id="bs-bagfluid" x="82" y="66" width="56" height="106" clip-path="url(#bs-bagclip)" fill="url(#bs-fluid)"/>
        <path d="M84,66 h52 v86 q0,14 -14,18 h-24 q-14,-4 -14,-18z" fill="none" stroke="#9FB6C2" stroke-width="1.5"/>
        <rect x="92" y="84" width="36" height="22" rx="3" fill="#fff" opacity=".9"/><text id="bs-bagname" x="110" y="98" class="bs-tiny" text-anchor="middle"></text>
        <text id="bs-baglevel" x="110" y="140" class="bs-lbl" text-anchor="middle"></text>
        <path d="M110,170 v10" stroke="#B9C9D2" stroke-width="3"/>
        <rect x="101" y="180" width="18" height="40" rx="6" fill="#F3FAFC" stroke="#9FB6C2"/>
        <rect id="bs-chamberpool" x="102" y="208" width="16" height="11" rx="4" fill="#D7EEF6"/>
        <g id="bs-drops"></g>
        <rect x="104" y="232" width="12" height="9" rx="2" fill="#7D8C95"/>
        <g id="bs-pump"><rect x="92" y="250" width="54" height="64" rx="7" fill="#F2F5F4" stroke="#9AA8AF"/><rect x="98" y="257" width="42" height="22" rx="3" fill="#0F2C3F"/>
          <text id="bs-pumprate" x="119" y="273" class="bs-pump" text-anchor="middle"></text><text x="119" y="292" class="bs-tiny" text-anchor="middle">mL/h</text>
          <circle id="bs-pumpled" cx="136" cy="304" r="3" fill="#3FE0B0"/></g>
        <text id="bs-dpm" x="148" y="206" class="bs-lbl"></text>
      </g>
      <path id="bs-ivtube" fill="none" stroke="#C9E4EE" stroke-width="3.2" stroke-linecap="round"/>
      <path id="bs-ivflow" fill="none" stroke="#7CC0DA" stroke-width="1.6" stroke-dasharray="3 9" stroke-linecap="round"/>
      <path id="bs-ngtube" fill="none" stroke="#E5D79A" stroke-width="3" stroke-linecap="round"/>

      <!-- monitor -->
      <g id="bs-monitor" class="bs-hit" data-open="obs" tabindex="0" role="button" aria-label="Patient monitor">
        <path d="M770,226 V250 Q770,262 790,262 H930" stroke="#8C9AA3" stroke-width="6" fill="none"/>
        <rect id="bs-monframe" x="610" y="32" width="324" height="194" rx="14" fill="#1B2A33" stroke="#33444F" stroke-width="2"/>
        <rect x="622" y="44" width="300" height="168" rx="6" fill="#06141C"/>
        <g clip-path="url(#bs-screen)">
          <polyline id="bs-ecg" fill="none" stroke="#3FE0B0" stroke-width="2" stroke-linejoin="round"/>
          <polyline id="bs-pleth" fill="none" stroke="#5BC8F5" stroke-width="2" stroke-linejoin="round"/>
          <polyline id="bs-resp" fill="none" stroke="#F2D26B" stroke-width="1.6" stroke-linejoin="round"/>
          <rect id="bs-cursor" y="44" width="10" height="168" fill="#06141C"/>
        </g>
        <text x="630" y="60" class="bs-mon-l" fill="#3FE0B0">II</text><text x="630" y="122" class="bs-mon-l" fill="#5BC8F5">Pleth</text><text x="630" y="172" class="bs-mon-l" fill="#F2D26B">Resp</text>
        <g class="bs-nums">
          <text x="912" y="78" id="bs-hr" class="bs-big" fill="#3FE0B0" text-anchor="end"></text><text x="912" y="56" class="bs-mon-l" fill="#3FE0B0" text-anchor="end">HR <tspan id="bs-heart">♥</tspan></text>
          <text x="912" y="128" id="bs-spo2" class="bs-big" fill="#5BC8F5" text-anchor="end"></text><text x="912" y="104" class="bs-mon-l" fill="#5BC8F5" text-anchor="end">SpO₂ %</text>
          <text x="912" y="178" id="bs-rr" class="bs-mid" fill="#F2D26B" text-anchor="end"></text><text x="912" y="158" class="bs-mon-l" fill="#F2D26B" text-anchor="end">RR</text>
          <text x="790" y="204" id="bs-nibp" class="bs-mid" fill="#F2F5F3" text-anchor="end"></text><text x="700" y="204" class="bs-mon-l" fill="#F2F5F3">NIBP</text>
          <text x="912" y="204" id="bs-temp" class="bs-mid" fill="#F3A6C8" text-anchor="end"></text>
        </g>
        <text id="bs-news" x="622" y="248" class="bs-lbl"></text>
      </g>
      <path id="bs-leads" fill="none" stroke="#C2CCD1" stroke-width="1.4" stroke-dasharray="2 3"/>

      <!-- bed -->
      <g id="bs-bed">
        <path d="M180,410 H830" stroke="#8C9AA3" stroke-width="10" stroke-linecap="round"/>
        <path d="M220,410 V452 M790,410 V452" stroke="#8C9AA3" stroke-width="7"/>
        <circle cx="220" cy="458" r="10" fill="#4F5A60"/><circle cx="790" cy="458" r="10" fill="#4F5A60"/>
        <rect x="826" y="268" width="14" height="146" rx="5" fill="#A3B1B8"/>
        <rect x="398" y="342" width="430" height="26" rx="8" fill="#E9EEF0" stroke="#C2CDD2"/>
        <path d="M400,368 L400,410" stroke="#8C9AA3" stroke-width="6"/>
        <g id="bs-rails-foot"><rect x="470" y="318" width="240" height="8" rx="4" fill="#B9C5CB"/><path d="M490,326 V342 M690,326 V342" stroke="#B9C5CB" stroke-width="5"/></g>
      </g>

      <!-- catheter bag (hangs on the frame) and chest drain (floor) -->
      <g id="bs-cath" class="bs-hit" data-open="catheter" tabindex="0" role="button" aria-label="Urinary catheter">
        <path d="M552,392 v-10 h20 v10" fill="none" stroke="#8C9AA3" stroke-width="3"/>
        <path d="M540,392 h44 v52 q0,10 -10,12 h-24 q-10,-2 -10,-12z" fill="#FBFAF2" stroke="#BDB58F"/>
        <rect id="bs-urine" x="538" y="392" width="48" height="66" clip-path="url(#bs-ubagclip)" fill="url(#bs-urine)"/>
        <path d="M540,392 h44 v52 q0,10 -10,12 h-24 q-10,-2 -10,-12z" fill="none" stroke="#BDB58F"/>
        ${[500, 1000, 1500].map(v => `<path d="M541,${456 - v / 2000 * 64} h7" stroke="#A39C76"/>`).join('')}
        <g id="bs-udrops"></g>
        <text id="bs-urinetxt" x="592" y="430" class="bs-lbl"></text>
      </g>
      <path id="bs-cathtube" fill="none" stroke="#E8E2B8" stroke-width="3" stroke-linecap="round"/>
      <g id="bs-drain" class="bs-hit" data-open="chest_drain" tabindex="0" role="button" aria-label="Chest drain">
        <rect x="450" y="412" width="48" height="56" rx="7" fill="#F3F7F8" stroke="#9FB0B7"/>
        <rect id="bs-drainfluid" x="450" y="440" width="48" height="28" clip-path="url(#bs-dclip)" fill="url(#bs-blood)" opacity=".8"/>
        <path d="M474,404 V452" stroke="#B9C9D2" stroke-width="3"/><g id="bs-drainbub"></g>
        <text id="bs-draintxt" x="474" y="490" class="bs-lbl" text-anchor="middle"></text>
      </g>
      <path id="bs-draintube" fill="none" stroke="#D9A3A9" stroke-width="3.2" stroke-linecap="round"/>

      <!-- traction at the foot -->
      <g id="bs-traction" class="bs-hit" data-open="traction" tabindex="0" role="button" aria-label="Traction">
        <circle cx="868" cy="300" r="9" fill="#8C9AA3"/><path d="M840,300 H868 M877,300 V380" stroke="#6C7A82" stroke-width="2"/>
        <path id="bs-tractrope" d="M780,300 H860" stroke="#6C7A82" stroke-width="2"/>
        <g id="bs-weight"><rect x="864" y="380" width="26" height="30" rx="4" fill="#4F5A60"/><text id="bs-wtxt" x="877" y="400" class="bs-tiny" fill="#fff" text-anchor="middle"></text></g>
      </g>

      <!-- patient: the foot section is flat; the head section rotates with the head of the bed -->
      <g id="bs-lower">
        <path id="bs-legs" d="M400,312 C470,304 560,300 640,306 C700,310 740,312 770,304 L792,300 Q800,316 790,338 L400,342Z" fill="url(#bs-blanket)"/>
        <path d="M770,304 Q786,276 798,284 Q800,300 792,312" fill="url(#bs-blanket)"/>
        <g id="bs-splint"><rect x="660" y="294" width="120" height="14" rx="7" fill="#F4F6F7" stroke="#C9D3D8"/><path d="M680,294 v14 M710,294 v14 M740,294 v14" stroke="#C9D3D8"/></g>
        <g id="bs-burnleg"><path d="M600,300 C640,296 700,298 760,300 L758,312 L600,314Z" fill="#fff" opacity=".92"/><path d="M610,302 l140,0 M612,308 l140,0" stroke="#E4E9EB" stroke-dasharray="6 4"/></g>
      </g>
      <g id="bs-upper">
        <rect x="180" y="342" width="222" height="26" rx="8" fill="#E9EEF0" stroke="#C2CDD2"/>
        <rect x="174" y="268" width="14" height="100" rx="5" fill="#A3B1B8"/>
        <g id="bs-rails-head"><rect x="250" y="318" width="130" height="8" rx="4" fill="#B9C5CB"/><path d="M268,326 V342 M362,326 V342" stroke="#B9C5CB" stroke-width="5"/></g>
        <ellipse cx="232" cy="330" rx="50" ry="14" fill="#FFFFFF" stroke="#D5DEE2"/>
        <g id="bs-chest"><path d="M276,326 C292,300 330,292 372,296 L402,300 L402,342 L276,342Z" fill="url(#bs-blanket)"/></g>
        <path d="M262,316 C268,304 280,302 288,308 L288,330 L262,330Z" fill="url(#bs-skin)"/>
        <g id="bs-head">
          <circle cx="246" cy="300" r="27" fill="url(#bs-skin)"/>
          <path d="M226,286 C226,268 248,262 262,272 C254,272 236,276 232,292Z" fill="#2B211C"/>
          <path d="M258,276 l9,-9 l-2,11" fill="url(#bs-skin)" stroke="#8E5E46" stroke-width=".8"/>
          <path id="bs-lips" d="M262,289 q4,2 6,-1" stroke="#8E4E46" stroke-width="2" fill="none" stroke-linecap="round"/>
          <path d="M252,281 q4,-2 7,0" stroke="#3A2A22" stroke-width="1.6" fill="none"/>
          <circle cx="244" cy="300" r="5" fill="#9A6A50"/>
          <g id="bs-headband"><path d="M222,290 C232,270 262,268 272,282" stroke="#fff" stroke-width="7" fill="none" stroke-linecap="round"/><circle cx="252" cy="274" r="3" fill="#D9545F"/></g>
          <g id="bs-fever"><path d="M236,262 q4,-6 0,-12 q-4,-6 0,-12 M250,258 q4,-6 0,-12 q-4,-6 0,-12" stroke="#E06A4F" stroke-width="1.6" fill="none" opacity=".75"/></g>
          <g id="bs-cannula"><path d="M262,280 q6,4 4,10" stroke="#B9DCEA" stroke-width="2.4" fill="none"/></g>
          <g id="bs-mask"><path d="M253,268 q14,-6 22,8 q2,12 -10,20 q-10,2 -14,-8z" fill="#E6F4F8" fill-opacity=".75" stroke="#9FC6D6" stroke-width="1.4"/>
            <ellipse id="bs-resbag" cx="290" cy="276" rx="12" ry="9" fill="#E6F4F8" stroke="#9FC6D6" stroke-width="1.2"/></g>
        </g>
        <g id="bs-collar"><path d="M264,300 C268,316 282,326 292,328 L292,306 C282,304 272,298 270,290Z" fill="#E8DCC4" stroke="#BFAF8E"/><path d="M270,300 l18,14" stroke="#BFAF8E"/></g>
      </g>
      <g id="bs-arm"></g>
      <g id="bs-cuff"></g>
      <g id="bs-labels"></g>
    </svg>`;
    return host.querySelector('svg');
  }

  /* ------------------------------------------------------------------ apply values → scene */
  function apply(svg, st) {
    const S = id => svg.getElementById ? svg.getElementById(id) : svg.querySelector('#' + id);
    const dev = st.devices, v = st.vitals || {}, d = derive(dev, st.patient.weight_kg);
    const deg = dev.bed.head_deg;
    S('bs-upper').setAttribute('transform', `rotate(${deg} ${HINGE[0]} ${HINGE[1]})`);
    const show = (id, on) => S(id).style.display = on ? '' : 'none';

    // patient appearance from the observations
    const spo2 = +v.spo2 || null, temp = +v.temperature_c || null;
    svg.style.setProperty('--bs-skin-1', spo2 && spo2 < 88 ? '#9A8A9C' : temp && temp >= 38.5 ? '#C98568' : temp && temp < 35 ? '#A3949A' : '#B9876A');
    svg.style.setProperty('--bs-skin-2', spo2 && spo2 < 88 ? '#7D6E85' : '#9A6A50');
    S('bs-lips').setAttribute('stroke', spo2 && spo2 < 90 ? '#5B5C9A' : '#8E4E46');
    show('bs-fever', temp && temp >= 38);
    const inj = st.injury, burns = inj ? inj.data.burns || [] : [];
    show('bs-headband', inj && (inj.data.head || burns.some(b => b.region === 'head')));
    show('bs-burnleg', burns.some(b => ['thigh', 'leg', 'foot'].includes(b.region)));
    show('bs-splint', dev.traction.on || (inj && (inj.data.injuries || []).some(x => x.type === 'fracture' && ['thigh', 'leg'].includes(x.region))));

    // key points that move with the head of the bed
    const nose = rot([266, 279], deg), chest = rot([340, 312], deg), shoulder = rot([300, 312], deg), neck = rot([276, 312], deg), side = rot([360, 336], deg);
    const hand = [470, 318];

    // arm lies on the blanket from the (rotating) shoulder to the hand; IV site and pulse oximeter on it
    const elbow = [(shoulder[0] + hand[0]) / 2 + 4, Math.max(shoulder[1], hand[1]) + 6];
    const burnArm = burns.some(b => ['upper_arm', 'forearm', 'hand'].includes(b.region));
    S('bs-arm').innerHTML = `<path d="M${shoulder[0]},${shoulder[1]} Q${elbow[0]},${elbow[1]} ${hand[0]},${hand[1]}" stroke="url(#bs-skin)" stroke-width="15" fill="none" stroke-linecap="round"/>
      ${burnArm ? `<path d="M${elbow[0] - 30},${elbow[1] - 2} Q${elbow[0] + 10},${elbow[1] + 2} ${hand[0] - 12},${hand[1]}" stroke="#fff" stroke-width="16" fill="none" stroke-linecap="round" opacity=".95"/>` : ''}
      <ellipse cx="${hand[0] + 6}" cy="${hand[1] + 1}" rx="13" ry="8" fill="url(#bs-skin)"/>
      <rect x="${hand[0] - 26}" y="${hand[1] - 6}" width="11" height="13" rx="3" fill="${st.patient.allergies.length ? '#D9384A' : '#F4F6F7'}" stroke="${st.patient.allergies.length ? '#A3202F' : '#C8D2D6'}"><title>${st.patient.allergies.length ? 'Red allergy band: ' + esc(st.patient.allergies.join(', ')) : 'ID band'}</title></rect>
      ${dev.pulse_ox.on ? `<g id="bs-probe"><rect x="${hand[0] + 14}" y="${hand[1] - 6}" width="14" height="11" rx="4" fill="#3A4A55"/><circle id="bs-probeled" cx="${hand[0] + 21}" cy="${hand[1] - .5}" r="2.6" fill="#FF3B4E"/></g>` : ''}`;
    S('bs-cuff').innerHTML = dev.bp_cuff.on ? `<rect id="bs-cuffband" x="${(shoulder[0] + elbow[0]) / 2 - 16}" y="${(shoulder[1] + elbow[1]) / 2 - 10}" width="32" height="19" rx="6" fill="#3E6E9A" stroke="#2B5276"/>` : '';

    // IV
    const iv = dev.iv;
    show('bs-iv', iv.on); show('bs-ivtube', iv.on); show('bs-ivflow', iv.on && iv.rate_ml_h > 0); show('bs-pump', iv.on && iv.pump);
    const site = iv.site === 'central' ? neck : iv.site.startsWith('acf') ? elbow : [hand[0] - 34, hand[1] - 2];
    const tube = `M110,241 C110,${iv.pump ? 330 : 300} ${site[0] - 140},${site[1] - 120} ${site[0]},${site[1]}`;
    S('bs-ivtube').setAttribute('d', tube); S('bs-ivflow').setAttribute('d', tube);
    S('bs-ivflow').style.animationDuration = `${Math.max(.4, 6 - Math.min(5.6, iv.rate_ml_h / 60))}s`;
    const lvl = iv.bag_ml ? iv.remaining_ml / iv.bag_ml : 0;
    const blood = iv.fluid === 'blood';
    S('bs-bagfluid').setAttribute('fill', blood ? 'url(#bs-blood)' : iv.fluid === 'plasma' ? '#F1D37C' : 'url(#bs-fluid)');
    S('bs-chamberpool').setAttribute('fill', blood ? '#B42634' : iv.fluid === 'plasma' ? '#F1D37C' : '#D7EEF6');
    S('bs-bagname').textContent = ({saline: 'NaCl 0.9%', ringers: "Ringer's", dextrose5: 'Dextrose 5%', dextrose_saline: 'D4% / NaCl', blood: 'Red cells', plasma: 'FFP', other: 'Infusion'})[iv.fluid];
    st.__bag = {level: lvl, y0: 66, h: 104, remaining: iv.remaining_ml, rate: iv.rate_ml_h, bag: iv.bag_ml, t0: performance.now()};
    S('bs-pumprate').textContent = rnd(iv.rate_ml_h, 1);
    S('bs-dpm').textContent = iv.on ? (iv.pump ? 'Pump' : `${d.drops_per_min}/min`) : '';

    // NG tube: nose → feed bag on the pole (feeding) or down beside the pillow (drainage)
    show('bs-ngtube', dev.ng_tube.on);
    S('bs-ngtube').setAttribute('d', dev.ng_tube.purpose === 'feeding' ? `M${nose[0]},${nose[1]} C${nose[0] - 20},${nose[1] - 70} 160,150 128,150` : `M${nose[0]},${nose[1]} C${nose[0] + 30},${nose[1] - 30} 330,360 300,400`);

    // oxygen
    const o2 = dev.oxygen;
    show('bs-o2', true); show('bs-o2tube', o2.on); show('bs-cannula', o2.on && ['nasal', 'hfnc'].includes(o2.device)); show('bs-mask', o2.on && ['mask', 'nrb', 'venturi'].includes(o2.device));
    S('bs-resbag').style.display = o2.on && o2.device === 'nrb' ? '' : 'none';
    S('bs-o2ball').setAttribute('cy', 154 - Math.min(15, o2.on ? o2.flow_l_min : 0) * 4.4);
    S('bs-o2txt').textContent = o2.on ? `${o2.flow_l_min} L/min · ~${d.fio2}% O₂` : 'Room air';
    S('bs-o2tube').setAttribute('d', `M216,218 C216,300 ${nose[0] - 60},${nose[1] + 40} ${nose[0]},${nose[1] + 4}`);

    // monitor leads to the chest
    S('bs-leads').setAttribute('d', dev.monitor.on ? `M650,226 C620,300 ${chest[0] + 80},${chest[1] - 40} ${chest[0]},${chest[1]} M690,226 C660,310 ${chest[0] + 90},${chest[1] - 20} ${chest[0] + 22},${chest[1] + 2}` : '');
    show('bs-monitor', dev.monitor.on);

    // catheter
    const c = dev.catheter;
    show('bs-cath', c.on); show('bs-cathtube', c.on);
    S('bs-cathtube').setAttribute('d', 'M520,342 C524,370 548,368 556,392');
    S('bs-urine').setAttribute('y', 456 - Math.min(1, c.bag_ml / 2000) * 64);
    S('bs-urine').setAttribute('fill', d.urine_ml_kg_h != null && d.urine_ml_kg_h < .5 ? '#C98A1E' : 'url(#bs-urine)');
    S('bs-urinetxt').textContent = c.on ? `${c.bag_ml} mL · ${c.output_ml_h} mL/h` : '';

    // chest drain
    const cd = dev.chest_drain;
    show('bs-drain', cd.on); show('bs-draintube', cd.on);
    S('bs-draintube').setAttribute('d', `M${side[0]},${side[1]} C${side[0] + 20},${side[1] + 50} 474,370 474,404`);
    S('bs-drainfluid').setAttribute('y', 468 - Math.min(1, cd.drainage_ml / 2500) * 52);
    S('bs-draintxt').textContent = cd.on ? `${cd.drainage_ml} mL${cd.bubbling ? ' · bubbling' : ''}` : '';

    // collar, traction, rails
    show('bs-collar', dev.collar.on);
    show('bs-traction', dev.traction.on);
    S('bs-wtxt').textContent = `${dev.traction.weight_kg} kg`;
    show('bs-rails-foot', dev.bed.rails); show('bs-rails-head', dev.bed.rails);

    // numbers on the monitor
    const n = news2(v);
    const parts = n ? n.parts : {};
    const tone = k => parts[k] >= 3 ? 'alarm-red' : parts[k] >= 2 ? 'alarm-amber' : '';
    const put = (id, txt, k) => { const e = S(id); e.textContent = txt; e.classList.remove('alarm-red', 'alarm-amber'); if (k && tone(k)) e.classList.add(tone(k)); };
    put('bs-hr', v.heart_rate ?? '--', 'heart_rate'); put('bs-spo2', v.spo2 ?? '--', 'spo2'); put('bs-rr', v.resp_rate ?? '--', 'resp_rate');
    put('bs-nibp', v.systolic ? `${v.systolic}/${v.diastolic ?? '--'}` : '--/--', 'systolic'); put('bs-temp', v.temperature_c != null ? `${v.temperature_c}°` : '--°', 'temperature_c');
    const worst = Math.max(0, ...Object.values(parts));
    S('bs-monframe').setAttribute('class', worst >= 3 ? 'mon-red' : worst >= 2 ? 'mon-amber' : '');
    S('bs-news').textContent = n ? `NEWS2 ${n.total} · ${({high: 'high risk', medium: 'medium risk', 'low-medium': 'one value scores 3', low: 'low risk'})[n.risk]}` : 'No observations yet';
    S('bs-news').setAttribute('class', `bs-lbl news-${n ? n.risk : 'none'}`);
    st.__derived = d; st.__news = n;
    return d;
  }

  /* ------------------------------------------------------------------ the animation loop */
  function run(svg, st) {
    const S = id => svg.querySelector('#' + id);
    const W = 300, X0 = 622, speed = 120;                         // px per second across the screen
    const traces = {ecg: {el: S('bs-ecg'), y: 86, amp: 30, pts: []}, pleth: {el: S('bs-pleth'), y: 146, amp: 26, pts: []}, resp: {el: S('bs-resp'), y: 196, amp: 10, pts: []}};
    for (const t of Object.values(traces)) t.pts = new Array(W).fill(t.y);
    let cursor = 0, last = performance.now(), clock = 0, nextDrop = 0, nextU = 0, nextBub = 0, nextDrainBub = 0, beatIx = -1, audio = null;
    const drops = S('bs-drops'), udrops = S('bs-udrops'), bub = S('bs-o2bub'), dbub = S('bs-drainbub');
    const chest = S('bs-chest'), resbag = S('bs-resbag'), heart = S('bs-heart');
    let raf;
    const spawn = (layer, cls, attrs, life) => { const e = document.createElementNS(NS, 'circle'); for (const k in attrs) e.setAttribute(k, attrs[k]); e.setAttribute('class', cls); layer.appendChild(e); setTimeout(() => e.remove(), life); };
    const beep = () => {
      if (!st.devices.monitor.sound) return;
      try { audio ||= new (window.AudioContext || window.webkitAudioContext)(); const o = audio.createOscillator(), g = audio.createGain();
        o.frequency.value = (+st.vitals.spo2 || 98) >= 94 ? 880 : 660; g.gain.value = .04; o.connect(g).connect(audio.destination); o.start(); o.stop(audio.currentTime + .07); } catch (e) { /* audio blocked */ }
    };
    function frame(now) {
      const dt = Math.min(.1, (now - last) / 1000); last = now; clock += dt;
      const v = st.vitals || {}, dev = st.devices, d = st.__derived || {};
      const hr = +v.heart_rate || 0, rr = +v.resp_rate || 0;
      // traces (sweep)
      const steps = Math.max(1, Math.round(speed * dt));
      for (let s = 0; s < steps; s++) {
        const t = clock - (steps - s) / speed;
        const phH = hr ? (t * hr / 60) % 1 : 0, phR = rr ? (t * rr / 60) % 1 : 0;
        traces.ecg.pts[cursor] = traces.ecg.y - (hr ? ecg(phH) : 0) * traces.ecg.amp;
        traces.pleth.pts[cursor] = traces.pleth.y - (hr && dev.pulse_ox.on ? pleth(phH) : 0) * traces.pleth.amp;
        traces.resp.pts[cursor] = traces.resp.y - (rr ? Math.sin(phR * Math.PI * 2) : 0) * traces.resp.amp;
        cursor = (cursor + 1) % W;
      }
      for (const tr of Object.values(traces)) tr.el.setAttribute('points', tr.pts.map((y, i) => `${X0 + i},${y.toFixed(1)}`).join(' '));
      S('bs-cursor').setAttribute('x', X0 + cursor);
      // heartbeat: heart symbol, probe LED, sound
      if (hr) {
        const ix = Math.floor(clock * hr / 60);
        const ph = (clock * hr / 60) % 1;
        if (ix !== beatIx) { beatIx = ix; beep(); }
        heart.setAttribute('opacity', ph < .18 ? 1 : .35);
        const led = svg.querySelector('#bs-probeled'); if (led) led.setAttribute('opacity', .35 + .65 * pleth(ph));
      }
      // breathing: chest rises and falls; reservoir bag empties on breathing in
      if (rr) {
        const b = (1 - Math.cos((clock * rr / 60) % 1 * Math.PI * 2)) / 2, amp = (+v.spo2 && +v.spo2 < 92) ? .09 : .05;
        chest.setAttribute('transform', `translate(0 ${(-b * 14 * amp / .05 * .4).toFixed(2)})`);
        if (resbag) resbag.setAttribute('ry', (9 - b * 4).toFixed(2));
      }
      // IV: drops at drops/min; bag level falls in real time
      if (dev.iv.on && d.drops_per_min > 0) {
        const period = 60 / d.drops_per_min;
        if (period < .35) { drops.innerHTML = '<rect x="109" y="186" width="2" height="22" fill="#9BD3E6"/>'; }
        else if (clock >= nextDrop) { if (drops.firstChild && drops.firstChild.tagName === 'rect') drops.innerHTML = ''; nextDrop = clock + period; spawn(drops, 'bs-drop', {cx: 110, cy: 186, r: 2.4}, 700); }
        const bg = st.__bag, mins = (now - bg.t0) / 60000, rem = Math.max(0, bg.remaining - bg.rate * mins / 60);
        const lvl = bg.bag ? rem / bg.bag : 0;
        S('bs-bagfluid').setAttribute('y', (bg.y0 + bg.h * (1 - lvl)).toFixed(2));
        S('bs-baglevel').textContent = `${Math.round(rem)} mL`;
      } else if (dev.iv.on) { const bg = st.__bag; S('bs-bagfluid').setAttribute('y', bg.y0 + bg.h * (1 - bg.level)); S('bs-baglevel').textContent = `${dev.iv.remaining_ml} mL`; drops.innerHTML = ''; }
      // urine: one visible drop for every ~2 mL (sped up so low outputs are still visible)
      if (dev.catheter.on && dev.catheter.output_ml_h > 0 && clock >= nextU) { nextU = clock + Math.max(.5, 3600 / dev.catheter.output_ml_h / 6); spawn(udrops, 'bs-udrop', {cx: 556, cy: 394, r: 1.8}, 900); }
      // oxygen bubbles: more flow, more bubbles
      if (dev.oxygen.on && clock >= nextBub) { nextBub = clock + Math.max(.08, .9 / dev.oxygen.flow_l_min); spawn(bub, 'bs-bub', {cx: 210 + Math.random() * 12, cy: 214, r: 1.3 + Math.random()}, 1200); }
      if (dev.chest_drain.on && dev.chest_drain.bubbling && clock >= nextDrainBub) { nextDrainBub = clock + .25 + Math.random() * .3; spawn(dbub, 'bs-bub', {cx: 474 + (Math.random() - .5) * 6, cy: 450, r: 1.6 + Math.random()}, 1100); }
      // BP cuff: inflates for 4 s at the start of each (sped-up) cycle
      const cuff = svg.querySelector('#bs-cuffband');
      if (cuff) { const cyc = clock % 20, inf = cyc < 4 ? Math.sin(cyc / 4 * Math.PI) : 0; cuff.setAttribute('transform', `scale(1 ${1 + inf * .45})`); cuff.style.transformOrigin = 'center'; cuff.style.transformBox = 'fill-box'; }
      raf = requestAnimationFrame(frame);
    }
    if (reduce) { frame(performance.now()); cancelAnimationFrame(raf); return () => {}; }
    raf = requestAnimationFrame(frame);
    return () => cancelAnimationFrame(raf);
  }

  /* ------------------------------------------------------------------ public */
  function mount(host, state) {
    const svg = build(host);
    const st = state;
    apply(svg, st);
    let stop = run(svg, st);
    return {
      svg, state: st,
      update(next) { Object.assign(st, next); apply(svg, st); },
      destroy() { stop(); },
    };
  }

  window.MFBedside = {mount, derive, news2, fio2};
})();
