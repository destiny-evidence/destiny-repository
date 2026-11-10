// FormField component for labeled input fields

import type { JSX } from "preact";

interface FormFieldProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  required?: boolean;
  type?: string;
  style?: JSX.CSSProperties;
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
    <div class="form-field">
      <label>{label}</label>
      <input
        type={type}
        value={value}
        onInput={(e) => onChange(e.currentTarget.value)}
        required={required}
        style={style}
      />
    </div>
  );
}
