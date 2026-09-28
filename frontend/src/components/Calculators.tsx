import { useEffect, useMemo, useRef, useState } from "react";
import { api, type FormulaInfo, type JsonSchema } from "../lib/api";

// Direct access to the same audited formulas the agent uses - handy for quick checks.

type Obj = Record<string, unknown>;

function resolve(s: JsonSchema, root: JsonSchema): JsonSchema {
  if (s.$ref) {
    const key = s.$ref.split("/").pop()!;
    return resolve(root.$defs?.[key] ?? {}, root);
  }
  if (s.anyOf) {
    const nonNull = s.anyOf.find((x) => x.type !== "null");
    return { ...resolve(nonNull ?? {}, root), description: s.description, default: s.default, title: s.title };
  }
  return s;
}

function defaults(s: JsonSchema, root: JsonSchema): unknown {
  const r = resolve(s, root);
  if (r.default !== undefined) return r.default;
  if (r.type === "object" && r.properties) {
    const o: Obj = {};
    for (const [k, v] of Object.entries(r.properties)) o[k] = defaults(v, root);
    return o;
  }
  if (r.type === "array") return [];
  if (r.enum) return r.enum[0];
  if (r.type === "number" || r.type === "integer") return r.format ? "" : 0;
  if (r.type === "boolean") return false;
  return "";
}

function Field({ name, schema, root, value, onChange }: { name: string; schema: JsonSchema; root: JsonSchema; value: unknown; onChange: (v: unknown) => void }) {
  const s = resolve(schema, root);
  const label = (
    <span className="field-label" title={s.description}>
      {name.replace(/_/g, " ")}
      {s.description && <span className="muted small"> — {s.description}</span>}
    </span>
  );
  if (s.type === "object" && s.properties) {
    return (
      <fieldset>
        <legend>{name.replace(/_/g, " ")}</legend>
        {Object.entries(s.properties).map(([k, v]) => (
          <Field key={k} name={k} schema={v} root={root} value={(value as Obj)?.[k]} onChange={(nv) => onChange({ ...(value as Obj), [k]: nv })} />
        ))}
      </fieldset>
    );
  }
  if (s.enum) {
    return (
      <label className="field">
        {label}
        <select value={String(value ?? "")} onChange={(e) => onChange(e.target.value)}>
          {s.enum.map((o) => (
            <option key={String(o)} value={String(o)}>{String(o)}</option>
          ))}
        </select>
      </label>
    );
  }
  if (s.type === "boolean") {
    return (
      <label className="field check">
        <input type="checkbox" checked={Boolean(value)} onChange={(e) => onChange(e.target.checked)} />
        {label}
      </label>
    );
  }
  if (s.type === "array") {
    return (
      <label className="field">
        {label}
        <textarea
          rows={4}
          defaultValue={JSON.stringify(value ?? [], null, 1)}
          onBlur={(e) => {
            try {
              onChange(JSON.parse(e.target.value || "[]"));
            } catch {
              alert(`${name}: invalid JSON`);
            }
          }}
        />
      </label>
    );
  }
  const numeric = s.type === "number" || s.type === "integer";
  return (
    <label className="field">
      {label}
      <input
        type={s.format === "date" ? "date" : numeric ? "number" : "text"}
        value={value === null || value === undefined ? "" : String(value)}
        onChange={(e) => onChange(numeric ? (e.target.value === "" ? null : Number(e.target.value)) : e.target.value || null)}
      />
    </label>
  );
}

function prune(v: unknown): unknown {
  if (Array.isArray(v)) return v;
  if (v && typeof v === "object") {
    const o: Obj = {};
    for (const [k, x] of Object.entries(v as Obj)) {
      const p = prune(x);
      if (p !== "" && p !== null && p !== undefined) o[k] = p;
    }
    return o;
  }
  return v;
}

export default function Calculators() {
  const [list, setList] = useState<FormulaInfo[]>([]);
  const [name, setName] = useState("income_tax_individual");
  const [schema, setSchema] = useState<JsonSchema | null>(null);
  const [values, setValues] = useState<Obj>({});
  const [result, setResult] = useState<Obj | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.formulas().then(setList).catch((e) => setErr(e.message));
  }, []);
  useEffect(() => {
    setResult(null);
    setErr(null);
    api.formula(name).then((f) => {
      setSchema(f.schema);
      setValues(defaults(f.schema, f.schema) as Obj);
    });
  }, [name]);

  const groups = useMemo(() => {
    const g: Record<string, FormulaInfo[]> = {};
    list.forEach((f) => (g[f.category] ||= []).push(f));
    return g;
  }, [list]);

  async function run() {
    setErr(null);
    try {
      setResult(await api.runFormula(name, prune(values)));
      rootRef.current?.scrollTo({ top: 0 });
    } catch (e) {
      setErr((e as Error).message);
      setResult(null);
    }
  }

  const steps = (result?.steps as string[] | undefined) ?? [];
  const main = result ? Object.entries(result).filter(([k, v]) => k !== "steps" && typeof v !== "object") : [];
  return (
    <div className="calc" ref={rootRef}>
      <div className="calc-list">
        {Object.entries(groups).map(([cat, fs]) => (
          <div key={cat}>
            <div className="muted small cat">{cat}</div>
            {fs.map((f) => (
              <button key={f.name} className={`calc-item${f.name === name ? " active" : ""}`} onClick={() => setName(f.name)} title={f.description}>
                {f.name.replace(/_/g, " ")}
              </button>
            ))}
          </div>
        ))}
      </div>
      <div className="calc-form">
        <h3>{name.replace(/_/g, " ")}</h3>
        <p className="muted small">{list.find((f) => f.name === name)?.description}</p>
        {schema?.properties &&
          Object.entries(schema.properties).map(([k, v]) => (
            <Field key={k} name={k} schema={v} root={schema} value={values[k]} onChange={(nv) => setValues({ ...values, [k]: nv })} />
          ))}
        <button onClick={run}>Calculate</button>
        {err && <pre className="error">{err}</pre>}
      </div>
      <div className="calc-result">
        {result ? (
          <>
            <table>
              <tbody>
                {main.map(([k, v]) => (
                  <tr key={k}>
                    <td>{k.replace(/_/g, " ")}</td>
                    <td className="num">{typeof v === "number" ? v.toLocaleString("en-IN", { maximumFractionDigits: 2 }) : String(v)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {steps.length > 0 && (
              <>
                <h4>Working</h4>
                <ol className="steps">{steps.map((s, i) => <li key={i}>{s}</li>)}</ol>
              </>
            )}
            <details>
              <summary className="muted small">Full JSON</summary>
              <pre>{JSON.stringify(result, null, 1)}</pre>
            </details>
          </>
        ) : (
          <p className="muted">Results with a step-by-step working appear here.</p>
        )}
      </div>
    </div>
  );
}
