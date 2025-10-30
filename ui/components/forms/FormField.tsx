// FormField component for labeled input fields

import React from "react";

interface FormFieldProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  required?: boolean;
  type?: string;
  style?: React.CSSProperties;
}

export default function FormField({
  label,
  value,
  onChange,
  required = false,
  type = "text",
  style,
}: FormFieldProps) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <label style={{ fontWeight: 500, color: "var(--primary-light)" }}>
        {label}
      </label>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        required={required}
        style={{
          border: "1px solid var(--primary-light)",
          borderRadius: "var(--border-radius)",
          padding: "10px 12px",
          fontSize: "1rem",
          background: "#fff",
          marginLeft: 0,
          ...style,
        }}
      />
    </div>
  );
}
