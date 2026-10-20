/** An indeterminate indicator, shown only while its request is pending. */
export default function LoadingSpinner({ label = "Loading", className = "" }: { label?: string; className?: string }) {
  return <span role="status" aria-label={label} className={`inline-flex items-center p-2 text-[#003366] ${className}`}>
    <span className="sr-only">{label}</span>
    <span aria-hidden="true" className="h-4 w-4 rounded-full border-2 border-current border-r-transparent motion-safe:animate-spin" />
  </span>;
}
