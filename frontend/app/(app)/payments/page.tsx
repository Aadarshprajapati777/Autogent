"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useWorkspace } from "@/components/workspace-provider";
import { CreditCard } from "lucide-react";

interface Payment {
  id: string;
  amount: number;
  currency: string;
  status: string;
  method: string | null;
  created_at: string | null;
}

export default function PaymentsPage() {
  const { workspace } = useWorkspace();
  const [payments, setPayments] = useState<Payment[]>([]);
  const [configured, setConfigured] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!workspace) return;
    setLoading(true);
    Promise.all([
      api<{ configured: boolean; currency: string }>("/payments/config"),
      api<{ count: number; payments: Payment[] }>(
        `/payments?workspace_id=${workspace.id}`,
      ),
    ])
      .then(([c, p]) => {
        setConfigured(c.configured);
        setPayments(p.payments);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [workspace]);

  if (!workspace) return null;

  return (
    <div className="p-6 lg:p-8">
      <div className="flex items-center gap-2">
        <CreditCard className="h-5 w-5 text-mint" />
        <h1 className="text-2xl font-bold">Payments</h1>
      </div>
      <p className="mt-1 text-sm text-zinc-500">
        Payment history via Razorpay.
      </p>

      {!configured && (
        <div className="mt-6 rounded-xl border border-amber-500/30 bg-amber-500/5 p-4">
          <p className="text-sm text-amber-400">
            Razorpay is not configured. Set RAZORPAY_KEY_ID and
            RAZORPAY_KEY_SECRET on the backend.
          </p>
        </div>
      )}

      <div className="mt-6 space-y-2">
        {loading ? (
          <div className="skeleton h-16 rounded-lg bg-white/5" />
        ) : payments.length === 0 ? (
          <div className="rounded-xl border border-line bg-panel p-8 text-center">
            <p className="text-sm text-zinc-600">No payments yet</p>
          </div>
        ) : (
          payments.map((p) => (
            <div
              key={p.id}
              className="flex items-center justify-between rounded-lg border border-line bg-panel px-4 py-3"
            >
              <div>
                <p className="text-sm font-medium">
                  {(p.amount / 100).toFixed(2)} {p.currency}
                </p>
                <p className="mt-0.5 text-xs text-zinc-600">
                  {p.method ?? "—"}
                  {p.created_at && ` · ${new Date(p.created_at).toLocaleDateString()}`}
                </p>
              </div>
              <span className="rounded-md bg-mint/15 px-2 py-0.5 text-xs text-mint">
                {p.status}
              </span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
