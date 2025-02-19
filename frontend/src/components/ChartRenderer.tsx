import { useMemo } from 'react'
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { ChartSpec } from '../lib/types'
import { formatNumber } from '../lib/format'
import { EmptyState } from './ui'
import { BarChart3 } from 'lucide-react'

const PALETTE = ['#3366ff', '#22c55e', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4', '#ec4899', '#84cc16']

function useSeries(spec: ChartSpec) {
  return useMemo(() => {
    const keys = spec.y_keys?.length ? spec.y_keys : Object.keys(spec.data[0] ?? {}).filter((k) => k !== spec.x_key)
    return keys.filter((key) => key !== 'series')
  }, [spec])
}

export function ChartRenderer({ spec, height = 300 }: { spec: ChartSpec; height?: number }) {
  const series = useSeries(spec)

  if (!spec?.data?.length) {
    return (
      <EmptyState
        title="No chart data"
        description="The chart specification did not contain any data points."
        icon={<BarChart3 size={28} />}
      />
    )
  }

  const type = spec.chart_type
  const title = <p className="mb-1 text-sm font-semibold">{spec.title}</p>

  if (type === 'pie' || type === 'donut') {
    const key = series[0]
    return (
      <div>
        {title}
        <div style={{ height }} className="w-full">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
            <Pie
              data={spec.data as never[]}
              dataKey={key}
              nameKey={spec.x_key}
              innerRadius={type === 'donut' ? '45%' : 0}
              outerRadius="70%"
              paddingAngle={1}
              stroke="none"
            >
              {spec.data.map((_, index) => (
                <Cell key={index} fill={PALETTE[index % PALETTE.length]} />
              ))}
            </Pie>
              <Tooltip formatter={(value: number) => formatNumber(value)} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
            </PieChart>
          </ResponsiveContainer>
        </div>
      </div>
    )
  }

  const common = {
    data: spec.data as never[],
    margin: { top: 8, right: 12, bottom: 4, left: 4 },
  }

  return (
    <div>
      {title}
      <div style={{ height }} className="w-full">
        <ResponsiveContainer width="100%" height="100%">
        {type === 'line' ? (
          <LineChart {...common}>
            <CartesianGrid strokeDasharray="3 3" stroke="#94a3b8" opacity={0.25} />
            <XAxis dataKey={spec.x_key} tick={{ fontSize: 11 }} tickLine={false} axisLine={false} />
            <YAxis tick={{ fontSize: 11 }} tickLine={false} axisLine={false} width={56} />
            <Tooltip formatter={(value: number) => formatNumber(value)} />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            {series.map((key, index) => (
              <Line
                key={key}
                type="monotone"
                dataKey={key}
                stroke={PALETTE[index % PALETTE.length]}
                strokeWidth={2}
                dot={spec.data.length < 40 ? { r: 2.5 } : false}
                activeDot={{ r: 4 }}
              />
            ))}
          </LineChart>
        ) : type === 'area' ? (
          <AreaChart {...common}>
            <CartesianGrid strokeDasharray="3 3" stroke="#94a3b8" opacity={0.25} />
            <XAxis dataKey={spec.x_key} tick={{ fontSize: 11 }} tickLine={false} axisLine={false} />
            <YAxis tick={{ fontSize: 11 }} tickLine={false} axisLine={false} width={56} />
            <Tooltip formatter={(value: number) => formatNumber(value)} />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            {series.map((key, index) => (
              <Area
                key={key}
                type="monotone"
                dataKey={key}
                stroke={PALETTE[index % PALETTE.length]}
                fill={PALETTE[index % PALETTE.length]}
                fillOpacity={0.18}
              />
            ))}
          </AreaChart>
        ) : (
          <BarChart {...common}>
            <CartesianGrid strokeDasharray="3 3" stroke="#94a3b8" opacity={0.25} vertical={false} />
            <XAxis
              dataKey={spec.x_key}
              tick={{ fontSize: 10 }}
              tickLine={false}
              axisLine={false}
              interval={0}
              angle={-18}
              textAnchor="end"
              height={54}
            />
            <YAxis tick={{ fontSize: 11 }} tickLine={false} axisLine={false} width={56} />
            <Tooltip formatter={(value: number) => formatNumber(value)} />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            {series.map((key, index) => (
              <Bar key={key} dataKey={key} fill={PALETTE[index % PALETTE.length]} radius={[4, 4, 0, 0]} />
            ))}
          </BarChart>
        )}
        </ResponsiveContainer>
      </div>
    </div>
  )
}
