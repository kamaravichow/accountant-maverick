// Convert between .xlsx/.csv files and FortuneSheet's sheet model.
// ExcelJS parses/writes xlsx in the browser (formulas preserved); FortuneSheet provides the
// Excel-like grid with a live formula engine so accountants can edit agent-built workpapers.

import ExcelJS from "exceljs";
import type { Sheet, Cell, CellWithRowAndCol } from "@fortune-sheet/core";

const INR_FMT = "##,##,##0.00";

function displayValue(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : v.toFixed(2);
  if (v instanceof Date) return v.toISOString().slice(0, 10);
  return String(v);
}

function excelCellToFortune(cell: ExcelJS.Cell): Cell | null {
  const val = cell.value as unknown;
  if (val === null || val === undefined || val === "") return null;
  const numFmt = cell.numFmt || "General";
  const out: Cell = {};
  let raw: unknown = val;
  if (typeof val === "object" && val !== null && !(val instanceof Date)) {
    const o = val as Record<string, unknown>;
    if ("formula" in o || "sharedFormula" in o) {
      const f = (o.formula as string) || "";
      if (f) out.f = `=${f}`;
      raw = o.result ?? "";
      if (raw && typeof raw === "object" && "error" in (raw as object)) raw = (raw as { error: string }).error;
    } else if ("richText" in o) {
      raw = (o.richText as { text: string }[]).map((t) => t.text).join("");
    } else if ("text" in o) {
      raw = o.text; // hyperlink
    } else if ("error" in o) {
      raw = o.error;
    }
  }
  if (raw instanceof Date) {
    out.v = raw.toISOString().slice(0, 10);
    out.m = out.v;
    out.ct = { fa: "yyyy-MM-dd", t: "d" };
    return out;
  }
  if (typeof raw === "number") {
    out.v = raw;
    out.m = displayValue(raw);
    out.ct = { fa: numFmt.includes("##") ? INR_FMT : numFmt === "General" ? "General" : numFmt, t: "n" };
  } else if (typeof raw === "boolean") {
    out.v = raw;
    out.m = raw ? "TRUE" : "FALSE";
    out.ct = { fa: "General", t: "b" };
  } else {
    out.v = String(raw ?? "");
    out.m = out.v;
    out.ct = { fa: "@", t: "s" };
  }
  if (cell.font?.bold) out.bl = 1;
  const fill = cell.fill as ExcelJS.FillPattern | undefined;
  const argb = fill?.fgColor?.argb;
  if (fill?.type === "pattern" && argb && argb.length === 8) out.bg = `#${argb.slice(2)}`;
  const fc = cell.font?.color?.argb;
  if (fc && fc.length === 8) out.fc = `#${fc.slice(2)}`;
  return out;
}

export type LoadedBook = { sheets: Sheet[]; workbook: ExcelJS.Workbook | null; kind: "xlsx" | "csv" };

export async function loadXlsx(buf: ArrayBuffer): Promise<LoadedBook> {
  const wb = new ExcelJS.Workbook();
  await wb.xlsx.load(buf);
  const sheets: Sheet[] = [];
  wb.eachSheet((ws, idx) => {
    const celldata: CellWithRowAndCol[] = [];
    const columnlen: Record<string, number> = {};
    ws.eachRow({ includeEmpty: false }, (row, r) => {
      row.eachCell({ includeEmpty: false }, (cell, c) => {
        const v = excelCellToFortune(cell);
        if (v) celldata.push({ r: r - 1, c: c - 1, v });
      });
    });
    ws.columns?.forEach((col, i) => {
      if (col && col.width) columnlen[String(i)] = Math.round(col.width * 7.5);
    });
    sheets.push({
      name: ws.name,
      id: `s${idx}`,
      order: sheets.length,
      status: sheets.length === 0 ? 1 : 0,
      celldata,
      row: Math.max(ws.rowCount + 30, 60),
      column: Math.max(ws.columnCount + 8, 26),
      config: { columnlen },
      luckysheet_select_save: [{ row: [0, 0], column: [0, 0] }],
    });
  });
  if (!sheets.length) sheets.push(blankSheet());
  return { sheets, workbook: wb, kind: "xlsx" };
}

export function blankSheet(name = "Sheet1"): Sheet {
  return { name, id: "s1", order: 0, status: 1, celldata: [], row: 60, column: 26, luckysheet_select_save: [{ row: [0, 0], column: [0, 0] }] };
}

export function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let field = "";
  let q = false;
  const delim = (text.split("\n")[0].match(/;/g)?.length ?? 0) > (text.split("\n")[0].match(/,/g)?.length ?? 0) ? ";" : ",";
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (q) {
      if (ch === '"' && text[i + 1] === '"') {
        field += '"';
        i++;
      } else if (ch === '"') q = false;
      else field += ch;
    } else if (ch === '"') q = true;
    else if (ch === delim) {
      row.push(field);
      field = "";
    } else if (ch === "\n" || ch === "\r") {
      if (ch === "\r" && text[i + 1] === "\n") i++;
      row.push(field);
      rows.push(row);
      row = [];
      field = "";
    } else field += ch;
  }
  if (field || row.length) {
    row.push(field);
    rows.push(row);
  }
  return rows;
}

export function loadCsv(text: string): LoadedBook {
  const celldata: CellWithRowAndCol[] = [];
  parseCsv(text).forEach((row, r) =>
    row.forEach((val, c) => {
      if (val === "") return;
      const num = Number(val.replace(/,/g, ""));
      const isNum = val.trim() !== "" && !Number.isNaN(num) && /^[-\d.,\s]+$/.test(val);
      celldata.push({ r, c, v: isNum ? { v: num, m: val, ct: { fa: "General", t: "n" } } : { v: val, m: val, ct: { fa: "@", t: "s" } } });
    }),
  );
  return { sheets: [{ ...blankSheet(), celldata, row: Math.max(celldata.length ? celldata[celldata.length - 1].r + 30 : 60, 60) }], workbook: null, kind: "csv" };
}

function matrixOf(sheet: Sheet): (Cell | null)[][] {
  if (sheet.data) return sheet.data;
  const m: (Cell | null)[][] = [];
  for (const cd of sheet.celldata ?? []) {
    (m[cd.r] ||= [])[cd.c] = cd.v;
  }
  return m;
}

function fortuneToExcelValue(cell: Cell | null): ExcelJS.CellValue {
  if (!cell) return null;
  if (cell.f) {
    const result = cell.v === undefined || cell.v === "" ? undefined : cell.v;
    return { formula: cell.f.replace(/^=/, ""), result } as ExcelJS.CellFormulaValue;
  }
  if (cell.v === undefined || cell.v === null || cell.v === "") return null;
  if (cell.ct?.t === "n" && typeof cell.v === "string" && cell.v.trim() !== "" && !Number.isNaN(Number(cell.v))) return Number(cell.v);
  return cell.v as ExcelJS.CellValue;
}

/** Write the grid back, keeping the original workbook's styles/column widths where possible. */
export async function saveXlsx(sheets: Sheet[], original: ExcelJS.Workbook | null): Promise<ArrayBuffer> {
  const wb = original ?? new ExcelJS.Workbook();
  const keep = new Set(sheets.map((s) => s.name));
  wb.worksheets.filter((ws) => !keep.has(ws.name)).forEach((ws) => wb.removeWorksheet(ws.id));
  for (const s of sheets) {
    const ws = wb.getWorksheet(s.name) ?? wb.addWorksheet(s.name);
    const m = matrixOf(s);
    const maxR = Math.max(m.length, ws.rowCount);
    for (let r = 0; r < maxR; r++) {
      const row = m[r] ?? [];
      const maxC = Math.max(row.length, ws.getRow(r + 1).cellCount);
      for (let c = 0; c < maxC; c++) {
        const val = fortuneToExcelValue(row[c] ?? null);
        const cell = ws.getCell(r + 1, c + 1);
        const cur = cell.value;
        if (val === null && (cur === null || cur === undefined)) continue;
        cell.value = val;
        if (row[c]?.bl) cell.font = { ...(cell.font ?? {}), bold: true };
      }
    }
  }
  wb.calcProperties = { ...(wb.calcProperties ?? {}), fullCalcOnLoad: true };
  return (await wb.xlsx.writeBuffer()) as ArrayBuffer;
}

export function toCsv(sheet: Sheet): string {
  const m = matrixOf(sheet);
  return m
    .map((row) =>
      (row ?? [])
        .map((cell) => {
          const s = cell?.m ?? cell?.v ?? "";
          const str = String(s);
          return /[",\n]/.test(str) ? `"${str.replace(/"/g, '""')}"` : str;
        })
        .join(","),
    )
    .join("\n");
}
