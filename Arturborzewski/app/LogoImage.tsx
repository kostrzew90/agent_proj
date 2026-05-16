'use client'

interface Props {
  alt: string
}

export default function LogoImage({ alt }: Props) {
  return (
    <img
      src="/images/logo.png"
      alt={alt}
      className="h-16 w-auto object-contain"
      onError={(e) => { e.currentTarget.style.display = 'none' }}
    />
  )
}
