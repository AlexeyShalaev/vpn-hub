import type { InputHTMLAttributes } from "react";
import { forwardRef } from "react";
import PhoneInput from "react-phone-number-input";
import flags from "react-phone-number-input/flags";
import "react-phone-number-input/style.css";
import "./phone-field.css";

// Инпут в стиле приложения (.input); react-phone-number-input сам форматирует и отдаёт E.164.
const StyledInput = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>((props, ref) => (
  <input {...props} ref={ref} className="input" />
));
StyledInput.displayName = "PhoneStyledInput";

export function PhoneField({
  value,
  onChange,
  autoFocus,
  onEnter,
}: {
  value: string;
  onChange: (v: string) => void;
  autoFocus?: boolean;
  onEnter?: () => void;
}) {
  return (
    <div className="phone-field" onKeyDown={onEnter ? (e) => e.key === "Enter" && onEnter() : undefined}>
      <PhoneInput
        international
        defaultCountry="RU"
        flags={flags}
        value={value || undefined}
        onChange={(v) => onChange(v ?? "")}
        inputComponent={StyledInput}
        autoFocus={autoFocus}
        placeholder="900 000-00-00"
      />
    </div>
  );
}
