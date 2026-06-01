"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";

import { fetchFarmer, fetchFarmerCalls, fetchInteractionRecords } from "@/lib/api";
import type { CallLog, FarmerProfile, InteractionRecord } from "@/types";

export default function FarmerDetailPage() {
  const params = useParams<{ phone_number: string }>();
  const router = useRouter();
  const phone = decodeURIComponent(params.phone_number);

  const [farmer, setFarmer] = useState<FarmerProfile | null>(null);
  const [calls, setCalls] = useState<CallLog[]>([]);
  const [interactions, setInteractions] = useState<InteractionRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    setLoading(true);
    Promise.all([
      fetchFarmer(phone),
      fetchFarmerCalls(phone),
      fetchInteractionRecords({ phone_number: phone, limit: 50 }),
    ])
      .then(([f, c, ir]) => {
        setFarmer(f);
        setCalls(c);
        setInteractions(ir);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [phone]);

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3 text-sm text-slate-500">
        <button
          onClick={() => router.push("/farmers")}
          className="hover:text-slate-700"
        >
          ← Back to farmers
        </button>
      </div>

      {loading && (
        <div className="bg-white rounded-xl border border-slate-200 p-8 animate-pulse">
          <div className="h-6 w-48 bg-slate-100 rounded mb-4" />
          <div className="h-4 w-64 bg-slate-100 rounded" />
        </div>
      )}

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-6">
          <p className="text-sm text-red-700">{error}</p>
        </div>
      )}

      {farmer && (
        <>
          <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-8 flex flex-col sm:flex-row gap-6 items-start">
            <div className="w-16 h-16 rounded-full bg-green-100 flex items-center justify-center text-green-700 font-semibold text-xl">
              {(farmer.name ?? farmer.phone_number ?? "?").slice(0, 2).toUpperCase()}
            </div>
            <div className="flex-1 grid grid-cols-1 sm:grid-cols-2 gap-x-8 gap-y-4">
              <Detail label="Name" value={farmer.name ?? "—"} />
              <Detail
                label="Phone"
                value={farmer.phone_number}
                mono
              />
              <Detail label="Location" value={farmer.location ?? "—"} />
              <Detail label="Language" value={farmer.language ?? "—"} />
              <Detail
                label="Farm size"
                value={
                  farmer.farm_size != null ? `${farmer.farm_size} ha` : "—"
                }
              />
              <Detail
                label="Crops"
                value={
                  Array.isArray(farmer.crops) && farmer.crops.length
                    ? farmer.crops.join(", ")
                    : "—"
                }
              />
              <Detail
                label="Registered"
                value={
                  farmer.registered_at
                    ? new Date(farmer.registered_at).toLocaleString()
                    : "—"
                }
              />
              <Detail label="Total calls" value={String(calls.length)} />
            </div>
          </div>

          <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
            <div className="px-8 py-6 border-b border-slate-100">
              <h3 className="text-base font-medium text-slate-800">
                Call history
                <span className="ml-2 text-sm font-normal text-slate-400">
                  ({calls.length})
                </span>
              </h3>
            </div>

            {calls.length === 0 ? (
              <div className="p-12 text-center text-sm text-slate-400">
                No call records yet.
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left">
                  <thead>
                    <tr className="border-b border-slate-100">
                      <th className="py-4 px-8 text-xs font-semibold text-slate-500 uppercase tracking-wide">
                        Session
                      </th>
                      <th className="py-4 px-8 text-xs font-semibold text-slate-500 uppercase tracking-wide">
                        When
                      </th>
                      <th className="py-4 px-8 text-xs font-semibold text-slate-500 uppercase tracking-wide">
                        Duration
                      </th>
                      <th className="py-4 px-8 text-xs font-semibold text-slate-500 uppercase tracking-wide text-right">
                        Action
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {calls.map((c) => (
                      <tr key={c.id} className="hover:bg-slate-50">
                        <td className="py-4 px-8 text-sm font-mono text-slate-600">
                          {c.session_id ?? "—"}
                        </td>
                        <td className="py-4 px-8 text-sm text-slate-600">
                          {c.timestamp
                            ? new Date(c.timestamp).toLocaleString()
                            : "—"}
                        </td>
                        <td className="py-4 px-8 text-sm text-slate-600">
                          {c.duration != null ? `${c.duration}s` : "—"}
                        </td>
                        <td className="py-4 px-8 text-right">
                          {c.session_id ? (
                            <Link
                              href={`/calls/${encodeURIComponent(c.session_id)}`}
                              className="text-sm font-medium text-blue-600 hover:text-blue-700"
                            >
                              Open transcript →
                            </Link>
                          ) : (
                            <span className="text-sm text-slate-300">
                              Unavailable
                            </span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
            <div className="px-8 py-6 border-b border-slate-100">
              <h3 className="text-base font-medium text-slate-800">
                Recent interactions
                <span className="ml-2 text-sm font-normal text-slate-400">
                  ({interactions.length})
                </span>
              </h3>
              <p className="text-sm text-slate-500 mt-1">
                Structured records (intent/entities/response type) emitted by the voice pipeline.
              </p>
            </div>

            {interactions.length === 0 ? (
              <div className="p-12 text-center text-sm text-slate-400">
                No interaction records yet.
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left">
                  <thead>
                    <tr className="border-b border-slate-100">
                      <th className="py-4 px-8 text-xs font-semibold text-slate-500 uppercase tracking-wide">
                        When
                      </th>
                      <th className="py-4 px-8 text-xs font-semibold text-slate-500 uppercase tracking-wide">
                        Session
                      </th>
                      <th className="py-4 px-8 text-xs font-semibold text-slate-500 uppercase tracking-wide">
                        Intent
                      </th>
                      <th className="py-4 px-8 text-xs font-semibold text-slate-500 uppercase tracking-wide">
                        Response type
                      </th>
                      <th className="py-4 px-8 text-xs font-semibold text-slate-500 uppercase tracking-wide">
                        Confidence
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {interactions.map((r) => (
                      <tr key={r.id} className="hover:bg-slate-50">
                        <td className="py-4 px-8 text-sm text-slate-600">
                          {r.created_at ? new Date(r.created_at).toLocaleString() : "—"}
                        </td>
                        <td className="py-4 px-8 text-sm font-mono text-slate-600">
                          {r.session_id ? (
                            <Link
                              href={`/calls/${encodeURIComponent(r.session_id)}`}
                              className="text-blue-600 hover:text-blue-700"
                            >
                              {r.session_id}
                            </Link>
                          ) : (
                            "—"
                          )}
                        </td>
                        <td className="py-4 px-8 text-sm text-slate-700">
                          {r.intent ?? "—"}
                        </td>
                        <td className="py-4 px-8 text-sm text-slate-700">
                          {r.response_type ?? "—"}
                        </td>
                        <td className="py-4 px-8 text-sm text-slate-700">
                          {r.confidence != null ? r.confidence.toFixed(3) : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}

function Detail({
  label,
  value,
  mono,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div>
      <span className="block text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1">
        {label}
      </span>
      <span className={`text-sm text-slate-900 ${mono ? "font-mono" : ""}`}>
        {value}
      </span>
    </div>
  );
}
