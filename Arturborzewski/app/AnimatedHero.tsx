"use client"
import { motion } from "framer-motion"
import { ReactNode } from "react"

const container = {
  hidden: {},
  visible: { transition: { staggerChildren: 0.2, delayChildren: 0.1 } },
}

const line = {
  hidden: { opacity: 0, y: 40 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.7, ease: [0.25, 0.46, 0.45, 0.94] as const },
  },
}

export function AnimatedHeroContainer({
  children,
  className,
}: {
  children: ReactNode
  className?: string
}) {
  return (
    <motion.div initial="hidden" animate="visible" variants={container} className={className}>
      {children}
    </motion.div>
  )
}

export function AnimatedHeroLine({
  children,
  className,
}: {
  children: ReactNode
  className?: string
}) {
  return (
    <motion.div variants={line} className={className}>
      {children}
    </motion.div>
  )
}
