"use client";
import { useState, type ReactNode, type Ref } from "react";
import { Dialog, DialogContent, DialogTitle, DialogDescription, DialogClose } from "@/components/ui/dialog";
export default function AdminModal({title, status, navigation, bodyRef, opener, children, onClose}: {
  title: string;
  status?: ReactNode;
  navigation?: ReactNode;
  bodyRef?: Ref<HTMLDivElement>;
  opener?: HTMLElement | null;
  children: ReactNode;
  onClose: () => void;
}) {
  const [returnFocus] = useState(() => typeof document !== "undefined" ? document.activeElement as HTMLElement | null : null);
  return (
    <Dialog open onOpenChange={open => { if (!open) onClose(); }}>
      <DialogContent showCloseButton={false} initialFocus={true} finalFocus={() => opener ?? returnFocus} className="admin-workspace admin-modal">
        <header className="admin-modal-header">
          <div>
            <DialogTitle>{title}</DialogTitle>
            <DialogDescription>Review the available evidence and permitted actions.</DialogDescription>
            {status}
          </div>
          <DialogClose className="admin-modal-close" aria-label="Close details">×</DialogClose>
        </header>
        {navigation}
        <div ref={bodyRef} className="admin-modal-body">{children}</div>
      </DialogContent>
    </Dialog>
  );
}
