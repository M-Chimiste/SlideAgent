import { useEffect, useState } from "react";
import { getJobStatus, regenerateSlide } from "../api/client";

type Props = {
  jobId: string | null;
};

export default function ReviewDownloadPage({ jobId }: Props) {
  const [status, setStatus] = useState<any | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!jobId) return;
    let timer: number | undefined;
    const fetchStatus = async () => {
      try {
        const response = await getJobStatus(jobId);
        setStatus(response);
      } catch (err: any) {
        setError(err.message || "Failed to load job.");
      }
    };
    fetchStatus();
    timer = window.setInterval(fetchStatus, 5000);
    return () => {
      if (timer) window.clearInterval(timer);
    };
  }, [jobId]);

  const handleRegen = async (slideIndex: number) => {
    if (!jobId) return;
    setLoading(true);
    setError("");
    try {
      await regenerateSlide(jobId, slideIndex);
      const response = await getJobStatus(jobId);
      setStatus(response);
    } catch (err: any) {
      setError(err.message || "Failed to regenerate slide.");
    } finally {
      setLoading(false);
    }
  };

  if (!jobId) {
    return (
      <div className="card">
        <h2>Review & Download</h2>
        <p className="status">No job selected yet.</p>
      </div>
    );
  }

  return (
    <div className="card">
      <h2>Review & Download</h2>
      {status && (
        <p className="status">
          Status: {status.job.status} • Progress:{" "}
          {Math.round(status.job.progress * 100)}%
        </p>
      )}
      {status?.job?.result_file && (
        <div className="row">
          <div className="column">
            <a href={`/api/jobs/${jobId}/download`}>
              <button type="button">Download PPTX</button>
            </a>
          </div>
          <div className="column">
            <a href={`/api/jobs/${jobId}/download?format=pdf`}>
              <button type="button" className="secondary">
                Download PDF
              </button>
            </a>
          </div>
        </div>
      )}
      {error && <p className="status">{error}</p>}
      {!!status?.warnings?.length && (
        <div className="card">
          <h3>Warnings</h3>
          <ul>
            {status.warnings.map((warning: any, idx: number) => (
              <li key={idx}>
                Slide {Number(warning.slide_index) + 1}: {warning.field} - {warning.message}
              </li>
            ))}
          </ul>
        </div>
      )}
      <div className="preview-grid">
        {status?.preview_images?.map((image: string, idx: number) => (
          <div key={image}>
            <img src={`/api/jobs/${jobId}/preview/${image}`} alt={image} />
            {status?.warnings?.some(
              (warning: any) => Number(warning.slide_index) === idx
            ) && <p className="status">Warning on this slide</p>}
            <button
              type="button"
              className="secondary"
              disabled={loading}
              onClick={() => handleRegen(idx)}
            >
              Regenerate Slide
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
