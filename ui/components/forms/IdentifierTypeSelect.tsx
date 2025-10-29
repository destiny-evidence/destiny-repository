// IdentifierTypeSelect component with hardcoded options

const options = [
  { value: "doi", label: "DOI" },
  { value: "open_alex", label: "OpenAlex" },
  { value: "pm_id", label: "Pubmed ID" },
  { value: "other", label: "Other" },
  { value: "destiny_id", label: "DESTINY ID" },
];

interface IdentifierTypeSelectProps {
  value: string;
  onChange: (value: string) => void;
}

export default function IdentifierTypeSelect({
  value,
  onChange,
}: IdentifierTypeSelectProps) {
  return (
    <label>
      Identifier Type:
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        style={{
          border: "1px solid var(--primary-light)",
          borderRadius: "var(--border-radius)",
          padding: "10px 12px",
          fontSize: "1rem",
          background: "#fff",
          marginLeft: 4,
        }}
      >
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
    </label>
  );
}
