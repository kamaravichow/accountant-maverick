import { useEffect, useMemo, useRef, useState } from "react";
import { TextInput } from "@astryxdesign/core/TextInput";
import { TextArea } from "@astryxdesign/core/TextArea";
import { NumberInput } from "@astryxdesign/core/NumberInput";
import { Selector } from "@astryxdesign/core/Selector";
import { CheckboxInput } from "@astryxdesign/core/CheckboxInput";
import { Button } from "@astryxdesign/core/Button";
import { Banner } from "@astryxdesign/core/Banner";
import { EmptyState } from "@astryxdesign/core/EmptyState";
import { VStack } from "@astryxdesign/core/Stack";
import { Heading, Text } from "@astryxdesign/core/Text";
import { Calculator, Search } from "lucide-react";
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

const title = (n: string) => {
  const t = n.replace(/_/g, " ");
  return t.charAt(0).toUpperCase() + t.slice(1);
};

function Field({ name, schema, root, value, onChange }: { name: string; schema: JsonSchema; root: JsonSchema; value: unknown; onChange: (v: unknown) => void }) {
  const s = resolve(schema, root);
  const label = title(name);
  const description = s.description || undefined;
  if (s.type === "object" && s.properties) {
    return (
      <fieldset className="calc-group">
        <legend>{label}</legend>
        {Object.entries(s.properties).map(([k, v]) => (
          <Field key={k} name={k} schema={v} root={root} value={(value as Obj)?.[k]} onChange={(nv) => onChange({ ...(value as Obj), [k]: nv })} />
        ))}
      </fieldset>
    );
  }
  if (s.enum) {
    return (
      <Selector
        label={label}
        description={description}
        options={s.enum.map((o) => ({ value: String(o), label: title(String(o)) }))}
        value={String(value ?? "")}
        onChange={(v) => onChange(v)}
        width="100%"
      />
    );
  }
  if (s.type === "boolean") return <CheckboxInput label={label} description={description} value={Boolean(value)} onChange={(c) => onChange(c)} />;
  if (s.type === "array") return <JsonArrayField label={label} description={description} value={value} onChange={onChange} />;
  if (s.type === "number" || s.type === "integer")
    return (
      <NumberInput
        label={label}
        description={description}
        value={typeof value === "number" ? value : null}
        onChange={(v) => onChange(v ?? null)}
        hasClear
        isIntegerOnly={s.type === "integer"}
        isWheelEnabled={false}
        formatValue={(n) => n.toLocaleString("en-IN", { maximumFractionDigits: 4 })}
        width="100%"
      />
    );
  if (s.format === "date")
    return (
      <label className="native-field">
        <Text type="label">{label}</Text>
        {description && <Text type="supporting">{description}</Text>}
        <input className="native-input" type="date" value={value ? String(value) : ""} onChange={(e) => onChange(e.target.value || null)} />
      </label>
    );
  return (
    <TextInput label={label} description={description} value={value === null || value === undefined ? "" : String(value)} onChange={(v) => onChange(v || null)} width="100%" />
  );
}

function JsonArrayField({ label, description, value, onChange }: { label: string; description?: string; value: unknown; onChange: (v: unknown) => void }) {
  const [text, setText] = useState(() => JSON.stringify(value ?? [], null, 1));
  const [bad, setBad] = useState(false);
  return (
    <TextArea
      label={label}
      description={description ? `${description} (JSON list)` : "JSON list"}
      value={text}
      rows={4}
      onChange={setText}
      onBlur={() => {
        try {
          onChange(JSON.parse(text || "[]"));
          setBad(false);
        } catch {
          setBad(true);
        }
      }}
      status={bad ? { type: "error", message: "Not valid JSON" } : undefined}
      width="100%"
    />
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
  const [query, setQuery] = useState("");
  const [formKey, setFormKey] = useState(0);
  const resultRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.formulas().then(setList).catch((e) => setErr(e.message));
  }, []);
  useEffect(() => {
    setResult(null);
    setErr(null);
    api.formula(name).then((f) => {
      setSchema(f.schema);
      setValues(defaults(f.schema, f.schema) as Obj);
      setFormKey((k) => k + 1);
    });
  }, [name]);

  const groups = useMemo(() => {
    const q = query.trim().toLowerCase();
    const g: Record<string, FormulaInfo[]> = {};
    list
      .filter((f) => !q || f.name.replace(/_/g, " ").includes(q) || f.description.toLowerCase().includes(q) || f.category.toLowerCase().includes(q))
      .forEach((f) => (g[f.category] ||= []).push(f));
    return g;
  }, [list, query]);

  async function run() {
    setErr(null);
    try {
      setResult(await api.runFormula(name, prune(values)));
      resultRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    } catch (e) {
      setErr((e as Error).message);
      setResult(null);
    }
  }

  const steps = (result?.steps as string[] | undefined) ?? [];
  const main = result ? Object.entries(result).filter(([k, v]) => k !== "steps" && typeof v !== "object") : [];
  const info = list.find((f) => f.name === name);
  return (
    <div className="calc">
      <nav className="calc-list" aria-label="Calculators">
        <div className="calc-search">
          <TextInput label="Search calculators" isLabelHidden placeholder="Search calculators…" value={query} onChange={setQuery} hasClear size="sm" startIcon={Search} width="100%" />
        </div>
        <div className="calc-list-scroll">
          {Object.entries(groups).map(([cat, fs]) => (
            <div key={cat} className="calc-cat">
              <div className="calc-cat-title">{cat}</div>
              {fs.map((f) => (
                <button key={f.name} className={`calc-item${f.name === name ? " active" : ""}`} aria-current={f.name === name} onClick={() => setName(f.name)} title={f.description}>
                  {title(f.name)}
                </button>
              ))}
            </div>
          ))}
          {!Object.keys(groups).length && <Text type="supporting">No calculators match “{query}”.</Text>}
        </div>
      </nav>
      <div className="calc-main">
        <form
          className="calc-form"
          onSubmit={(e) => {
            e.preventDefault();
            run();
          }}
        >
          <VStack gap={1}>
            {info && <Text type="supporting" size="xsm">{info.category}</Text>}
            <Heading level={2}>{title(name)}</Heading>
            {info?.description && <Text type="supporting" as="p">{info.description}</Text>}
          </VStack>
          <div className="calc-fields" key={formKey}>
            {schema?.properties &&
              Object.entries(schema.properties).map(([k, v]) => (
                <Field key={k} name={k} schema={v} root={schema} value={values[k]} onChange={(nv) => setValues((cur) => ({ ...cur, [k]: nv }))} />
              ))}
          </div>
          <div className="calc-actions">
            <Button label="Calculate" variant="primary" type="submit" icon={<Calculator size={16} />} />
            <Button label="Reset" variant="ghost" onClick={() => schema && (setValues(defaults(schema, schema) as Obj), setResult(null), setFormKey((k) => k + 1))} />
          </div>
          {err && <Banner status="error" title="Calculation failed" description={<pre className="plain-pre">{err}</pre>} />}
        </form>
        <section className="calc-result" ref={resultRef} aria-label="Result">
          {result ? (
            <>
              <Text type="label" weight="semibold">Result</Text>
              <table>
                <tbody>
                  {main.map(([k, v]) => (
                    <tr key={k}>
                      <td>{title(k)}</td>
                      <td className="num">{typeof v === "number" ? v.toLocaleString("en-IN", { maximumFractionDigits: 2 }) : String(v)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {steps.length > 0 && (
                <>
                  <Text type="label" weight="semibold">Working</Text>
                  <ol className="steps">{steps.map((s, i) => <li key={i}>{s}</li>)}</ol>
                </>
              )}
              <details className="raw">
                <summary>Full JSON</summary>
                <pre>{JSON.stringify(result, null, 1)}</pre>
              </details>
            </>
          ) : (
            <EmptyState isCompact title="No result yet" description="Fill in the inputs and press Calculate. The result appears here with a step-by-step working." icon={<Calculator size={24} />} />
          )}
        </section>
      </div>
    </div>
  );
}
