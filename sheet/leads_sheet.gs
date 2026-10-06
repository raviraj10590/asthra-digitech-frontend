/**
 * Bairavi Leads — Google Sheet <-> CRM (Apps Script, bound to the sheet).
 *
 * Owner, 2026-10-06: the marketing team opens this sheet, calls the leads and
 * writes what happened; the CRM must know what they wrote.
 *
 *   refresh()     every 15 min: pulls every Bairavi lead from the Brain
 *                 (/api/leads_sheet) and rewrites columns A–I, keeping each
 *                 row's Team note by its CRM id — new leads arrive on top, so
 *                 a note can never slide onto the wrong person.
 *   onTeamNote()  when someone types in "Team note", sends it to the Brain,
 *                 which appends "📝 06 Oct 15:40 Sheet (name): …" to that
 *                 lead's CRM notes; column K shows ✓ and the time.
 *
 * Install once: Extensions → Apps Script → paste this file → set KEY → Run
 * setup() → Allow. Nothing else to do; the sheet keeps itself up to date.
 */
const KEY = 'PASTE_LEADS_SHEET_KEY_HERE';
const URL = 'https://asthra-digitech-frontend.vercel.app/api/leads_sheet?key=' + encodeURIComponent(KEY);
const SHEET = 'Leads';
const ID_COL = 9;       // I  CRM id (hidden)
const NOTE_COL = 10;    // J  Team note — the marketing team types here
const STATUS_COL = 11;  // K  Saved to CRM
const WIDTH = STATUS_COL;

function setup() {
  ScriptApp.getProjectTriggers().forEach(function (t) { ScriptApp.deleteTrigger(t); });
  ScriptApp.newTrigger('refresh').timeBased().everyMinutes(15).create();
  ScriptApp.newTrigger('onTeamNote').forSpreadsheet(SpreadsheetApp.getActive()).onEdit().create();
  refresh();
  style_(sheet_());
}

function onOpen() {
  SpreadsheetApp.getUi().createMenu('Bairavi').addItem('Refresh leads now', 'refresh').addToUi();
}

function sheet_() {
  var ss = SpreadsheetApp.getActive();
  return ss.getSheetByName(SHEET) || ss.getSheets()[0];
}

function refresh() {
  var sh = sheet_();
  var res = UrlFetchApp.fetch(URL, { muteHttpExceptions: true });
  if (res.getResponseCode() !== 200) throw new Error('Leads fetch failed: HTTP ' + res.getResponseCode());
  var rows = Utilities.parseCsv(res.getContentText('UTF-8'));
  var header = rows.shift();
  var lock = LockService.getDocumentLock();
  lock.waitLock(20000);
  try {
    // Team notes already in the sheet, by CRM id
    var keep = {};
    var last = sh.getLastRow();
    if (last > 1) {
      sh.getRange(2, 1, last - 1, WIDTH).getValues().forEach(function (v) {
        if (v[ID_COL - 1]) keep[v[ID_COL - 1]] = [v[NOTE_COL - 1], v[STATUS_COL - 1]];
      });
    }
    var out = rows.filter(function (r) { return r.length >= ID_COL; }).map(function (r) {
      var k = keep[r[ID_COL - 1]] || ['', ''];
      return r.slice(0, ID_COL).concat(k);
    });
    sh.getRange(1, 1, 1, WIDTH).setValues([header.slice(0, ID_COL).concat(['Team note ✍️ (type here)', 'Saved to CRM'])]);
    if (last > 1) sh.getRange(2, 1, last - 1, WIDTH).clearContent();
    if (out.length) {
      var rng = sh.getRange(2, 1, out.length, WIDTH);
      rng.setNumberFormat('@');          // dates and phones stay exactly as sent
      rng.setValues(out);
    }
    sh.hideColumns(ID_COL);
  } finally {
    lock.releaseLock();
  }
}

function onTeamNote(e) {
  var r = e.range;
  var sh = r.getSheet();
  if (sh.getName() !== sheet_().getName() || r.getColumn() !== NOTE_COL || r.getRow() < 2 || r.getNumRows() !== 1) return;
  var note = String(r.getValue() || '').trim();
  var status = sh.getRange(r.getRow(), STATUS_COL);
  // Added to a note already saved: send only the new words, not all of it again
  var old = String(e.oldValue || '').trim();
  if (old && note.indexOf(old) === 0) note = note.slice(old.length).replace(/^[\s,.;:-]+/, '');
  if (!note) return;
  var id = sh.getRange(r.getRow(), ID_COL).getValue();
  if (!id) { status.setValue('✗ no CRM id — refresh and type again'); return; }
  var by = '';
  try { by = (e.user && e.user.getEmail ? e.user.getEmail() : '').split('@')[0]; } catch (err) {}
  var res = UrlFetchApp.fetch(URL, {
    method: 'post', contentType: 'application/json', muteHttpExceptions: true,
    payload: JSON.stringify({ id: id, note: note, by: by })
  });
  status.setValue(res.getResponseCode() === 200
    ? '✓ ' + Utilities.formatDate(new Date(), 'Asia/Kolkata', 'dd MMM HH:mm')
    : '✗ not saved (HTTP ' + res.getResponseCode() + ') — type it again');
}

function style_(sh) {
  sh.setFrozenRows(1);
  sh.getRange(1, 1, 1, WIDTH).setBackground('#0B2A5B').setFontColor('#FFFFFF').setFontWeight('bold')
    .setVerticalAlignment('middle').setHorizontalAlignment('center').setWrap(true);
  sh.getRange(1, NOTE_COL).setBackground('#F0B429').setFontColor('#0B2A5B');
  sh.getRange(2, NOTE_COL, sh.getMaxRows() - 1, 1).setBackground('#FFFBEA').setWrap(true);
  sh.getRange(2, STATUS_COL, sh.getMaxRows() - 1, 1).setFontColor('#1E7A3C');
  sh.setColumnWidth(NOTE_COL, 320);
  sh.setColumnWidth(STATUS_COL, 150);
}
