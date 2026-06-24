'use client'

import { useState } from 'react'
import LogoImage from './LogoImage'

interface Props {
  src: string
  alt: string
  className?: string
}

export default function HeroImage({ src, alt, className }: Props) {
  const [failed, setFailed] = useState(false)

  if (failed) {
    return (
      <div className={`${className} flex items-center justify-center bg-gradient-to-br from-zinc-900 via-black to-zinc-950`}>
        <LogoImage
          alt={alt}
          src="/images/logo-mono.png"
          className="w-2/3 max-w-[220px] object-contain opacity-80"
        />
      </div>
    )
  }

  return (
    <img
      src={src}
      alt={alt}
      className={className}
      onError={() => setFailed(true)}
    />
  )
}
