'use client'

interface Props {
  alt: string
  src?: string
  className?: string
}

export default function LogoImage({ alt, src = '/images/logo-pelne.webp', className = 'h-14 w-auto object-contain' }: Props) {
  return (
    <img
      src={src}
      alt={alt}
      className={className}
      onError={(e) => { e.currentTarget.style.display = 'none' }}
    />
  )
}
