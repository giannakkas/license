"use client";

/**
 * A submit button that asks before it fires. Its own `name`/`value` say what it does, so a form
 * holding several buttons only ever sends the action of the button that was clicked.
 */
export function ConfirmButton({
  children,
  message,
  className,
  name = "action",
  value,
}: {
  children: React.ReactNode;
  message: string;
  className?: string;
  name?: string;
  value: string;
}) {
  return (
    <button
      type="submit"
      name={name}
      value={value}
      className={className ?? "btn btn-danger btn-small"}
      onClick={(event) => {
        if (!window.confirm(message)) event.preventDefault();
      }}
    >
      {children}
    </button>
  );
}
