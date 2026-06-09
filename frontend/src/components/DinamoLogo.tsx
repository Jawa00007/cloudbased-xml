export default function DinamoLogo({ size = 32 }: { size?: number }) {
  return (
    <img
      src="/quanta-logo.jpg"
      alt="Quanta"
      width={size}
      height={size}
      style={{ width: size, height: size, objectFit: 'contain', borderRadius: 6 }}
    />
  )
}
