export default function StagePlaceholder({ stage, title, description }) {
  return (
    <div className="placeholder-card">
      <div className="placeholder-stage">{stage}</div>
      <h1>{title}</h1>
      <p>{description}</p>
    </div>
  )
}
