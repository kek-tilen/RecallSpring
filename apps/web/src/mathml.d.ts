// MathML elements for JSX: React renders them in the MathML namespace; @types/react does not list them.
import type { ClassAttributes, HTMLAttributes } from "react";

interface MathMLAttributes extends HTMLAttributes<Element>, ClassAttributes<Element> {
  display?: "block" | "inline";
  mathvariant?: "normal";
  stretchy?: string;
  movablelimits?: string;
  largeop?: string;
  symmetric?: string;
  minsize?: string;
  maxsize?: string;
  accent?: string;
  accentunder?: string;
  linethickness?: string;
  width?: string;
  form?: "prefix" | "infix" | "postfix";
}

declare module "react" {
  namespace JSX {
    interface IntrinsicElements {
      math: MathMLAttributes;
      mi: MathMLAttributes;
      mn: MathMLAttributes;
      mo: MathMLAttributes;
      mtext: MathMLAttributes;
      mrow: MathMLAttributes;
      mfrac: MathMLAttributes;
      msqrt: MathMLAttributes;
      mroot: MathMLAttributes;
      msub: MathMLAttributes;
      msup: MathMLAttributes;
      msubsup: MathMLAttributes;
      munder: MathMLAttributes;
      mover: MathMLAttributes;
      munderover: MathMLAttributes;
      mspace: MathMLAttributes;
      mtable: MathMLAttributes;
      mtr: MathMLAttributes;
      mtd: MathMLAttributes;
      mphantom: MathMLAttributes;
    }
  }
}
