export default function DinamoLogo({ size = 32 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 100 165"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      {/* Outer navy swoop — large sweeping arc */}
      <path
        d="M78 8 C105 28 110 68 88 100 C68 130 18 138 10 162"
        stroke="#152164"
        strokeWidth="17"
        strokeLinecap="round"
        fill="none"
      />
      {/* Crossing navy sweep — horizontal interceptor */}
      <path
        d="M4 58 C38 44 90 66 74 94 C58 120 14 120 6 144"
        stroke="#152164"
        strokeWidth="13"
        strokeLinecap="round"
        fill="none"
      />
      {/* Magenta accent stripe */}
      <path
        d="M46 4 C56 46 60 96 44 150 C40 162 36 168 30 172"
        stroke="#C400CC"
        strokeWidth="16"
        strokeLinecap="round"
        fill="none"
      />
    </svg>
  )
}
