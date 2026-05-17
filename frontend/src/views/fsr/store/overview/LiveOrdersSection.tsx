// Live Call Orders — latest 10 orders + pending payment badge + manual refresh.
// (실시간 통화 주문 — 최근 10건 + 미결제 badge + 수동 새로고침)
import { useEffect, useState } from 'react'
import api from '../../../../core/api'
import Skeleton from '../../../../components/Skeleton/Skeleton'
import styles from '../Overview.module.css'

interface Order {
  id: number
  customer_phone: string | null
  customer_email: string | null
  total_amount: number
  status: string
  created_at: string
  items: Array<{ name?: string; quantity?: number }>
}

const fmt = (n: number) =>
  `$${n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`

const fmtDate = (iso: string) => {
  try {
    return new Date(iso).toLocaleDateString('en-US', {
      month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
    })
  } catch { return iso }
}

export default function LiveOrdersSection() {
  const [orders, setOrders] = useState<Order[]>([])
  const [loading, setLoading] = useState(true)

  const refresh = () => {
    setLoading(true)
    api
      .get('/store/orders?limit=10')
      .then((r) => setOrders(r.data))
      .finally(() => setLoading(false))
  }

  useEffect(() => { refresh() }, [])

  const pendingCount = orders.filter((o) => o.status === 'fired_unpaid').length

  return (
    <div className={styles.ordersPanel}>
      <div className={styles.panelHeader}>
        <span className={styles.panelIcon}>🛒</span>
        <div>
          <div className={styles.panelTitle}>Live Call Orders</div>
          <div className={styles.panelDesc}>Latest 10 orders placed via the AI voice assistant.</div>
        </div>
        {pendingCount > 0 && (
          <span className={styles.pendingBadge} title="Orders fired without payment yet">
            ⚠ {pendingCount} pending payment
          </span>
        )}
        <button className={styles.refreshBtn} onClick={refresh}>↺ Refresh</button>
      </div>

      {loading ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, padding: '8px 0' }}>
          {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} h={36} radius={6} />)}
        </div>
      ) : orders.length === 0 ? (
        <div className={styles.empty}>No orders yet</div>
      ) : (
        <table className={styles.ordersTable}>
          <thead>
            <tr>
              <th>ORDER ID</th>
              <th>CUSTOMER NAME</th>
              <th>TOTAL AMOUNT</th>
              <th>STATUS</th>
              <th>DATE</th>
            </tr>
          </thead>
          <tbody>
            {orders.map((o) => (
              <tr key={o.id}>
                <td className={styles.orderId}>#{o.id}</td>
                <td>{o.customer_email?.split('@')[0] ?? o.customer_phone ?? '—'}</td>
                <td className={`${styles.orderAmount} ${o.status === 'paid' ? styles.orderAmountPaid : ''}`}>
                  {fmt(o.total_amount)}
                </td>
                <td>
                  <span className={`${styles.statusBadge} ${o.status === 'paid' ? styles.statusPaid : styles.statusPending}`}>
                    {o.status}
                  </span>
                </td>
                <td className={styles.orderDate}>{fmtDate(o.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
