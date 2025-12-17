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
    <div className="form-field">
      <label>{label}</label>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        required={required}
        style={style}
      />
    </div>
  );
}
