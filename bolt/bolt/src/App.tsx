import { useState, useCallback, useEffect, useRef } from 'react';
import { Toolbar } from '@/components/Toolbar';
import { FftPlot } from '@/components/FftPlot';
import { Waterfall } from '@/components/Waterfall';
import { DetectionsPanel } from '@/components/DetectionsPanel';
import { FileInfoPanel } from '@/components/FileInfoPanel';
import { PipelineLogPanel } from '@/components/PipelineLogPanel';
import { StatusBar } from '@/components/StatusBar';
import { SignalBreakdown } from '@/components/SignalBreakdown';
import { DockPanel } from '@/components/DockPanel';
import { DetectionDetailPanel } from '@/components/DetectionDetailPanel';
import { ColormapLegend } from '@/components/ColormapLegend';
import { WelcomeScreen } from '@/components/WelcomeScreen';
import { ChevronDown, ChevronUp } from 'lucide-react';
import type {
  AnalyzeResponse,
  SpectrogramResponse,
  DetectionLayersResponse,
  FileInfo,
  Detection,
} from '@/lib/types';
import {
  generateMockAnalyze,
  generateMockSpectrogram,
  generateMockLayers,
  getMockFileInfo,
} from '@/lib/mockData';
import { cn } from '@/lib/utils';

export function App() {
  const [file, setFile] = useState<File | null>(null);
  const [fileInfo, setFileInfo] = useState<FileInfo | null>(null);
  const [analysis, setAnalysis] = useState<AnalyzeResponse | null>(null);
  const [spectrogram, setSpectrogram] = useState<SpectrogramResponse | null>(null);
  const [layers, setLayers] = useState<DetectionLayersResponse | null>(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [isLoadingSpectrogram, setIsLoadingSpectrogram] = useState(false);
  const [isLoadingLayers, setIsLoadingLayers] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedDetectionId, setSelectedDetectionId] = useState<string | null>(null);
  const [thresholdDb, setThresholdDb] = useState(-75.0);
  const [cursorFreq, setCursorFreq] = useState<number | null>(null);
  const [cursorPower, setCursorPower] = useState<number | null>(null);
  const [cursorTime, setCursorTime] = useState<number | null>(null);
  const [breakdownOpen, setBreakdownOpen] = useState(true);
  const [psdData, setPsdData] = useState<{ freqs: number[]; magnitudes: number[] } | null>(null);

  const useMockData = useRef(true);

  const freqMin = analysis ? -analysis.sample_rate! / 2 : -1_000_000;
  const freqMax = analysis ? analysis.sample_rate! / 2 : 1_000_000;
  const dbMin = -120;
  const dbMax = -20;
  const sampleRate = analysis?.sample_rate ?? 2_000_000;
  const totalSamples = analysis ? analysis.sample_rate! * analysis.duration_seconds! : 1_000_000;

  const handleFileOpen = useCallback((f: File) => {
    setFile(f);
    setFileInfo(getMockFileInfo(f));
    setAnalysis(null);
    setSpectrogram(null);
    setLayers(null);
    setSelectedDetectionId(null);
    setPsdData(null);
    setError(null);
  }, []);

  const handleAnalyze = useCallback(async () => {
    if (!file) return;
    setIsAnalyzing(true);
    setError(null);
    try {
      let result: AnalyzeResponse;
      if (useMockData.current) {
        await new Promise((r) => setTimeout(r, 800));
        result = generateMockAnalyze(file);
      } else {
        const { analyzeFile } = await import('@/lib/api');
        result = await analyzeFile(file);
      }
      setAnalysis(result);
      setThresholdDb(result.noise_floor_db + 17);

      setIsLoadingSpectrogram(true);
      let spectrogramResult: SpectrogramResponse;
      if (useMockData.current) {
        await new Promise((r) => setTimeout(r, 500));
        spectrogramResult = generateMockSpectrogram();
      } else {
        const { fetchSpectrogram } = await import('@/lib/api');
        spectrogramResult = await fetchSpectrogram(result.job_id);
      }
      setSpectrogram(spectrogramResult);
      setIsLoadingSpectrogram(false);

      if (spectrogramResult.magnitude_2d.length > 0) {
        const freqBins = spectrogramResult.freq_bins;
        const timeBins = spectrogramResult.magnitude_2d.length;
        const avgMags: number[] = new Array(freqBins.length).fill(0);
        for (let t = 0; t < timeBins; t++) {
          for (let f = 0; f < freqBins.length; f++) {
            avgMags[f] += spectrogramResult.magnitude_2d[t][f] / timeBins;
          }
        }
        setPsdData({ freqs: freqBins, magnitudes: avgMags });
      }

      if (result.detections.length > 0) {
        setSelectedDetectionId(result.detections[0].id);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Analysis failed');
    } finally {
      setIsAnalyzing(false);
    }
  }, [file]);

  useEffect(() => {
    if (!selectedDetectionId || !analysis) {
      setLayers(null);
      return;
    }
    setIsLoadingLayers(true);
    const fetchLayers = async () => {
      try {
        let result: DetectionLayersResponse;
        if (useMockData.current) {
          await new Promise((r) => setTimeout(r, 400));
          result = generateMockLayers(selectedDetectionId);
        } else {
          const { fetchDetectionLayers } = await import('@/lib/api');
          result = await fetchDetectionLayers(analysis.job_id, selectedDetectionId);
        }
        setLayers(result);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load layers');
      } finally {
        setIsLoadingLayers(false);
      }
    };
    fetchLayers();
  }, [selectedDetectionId, analysis]);

  const handleSelectDetection = useCallback((id: string) => {
    setSelectedDetectionId(id);
  }, []);

  const handleFftCursorMove = useCallback((freq: number | null, mag: number | null) => {
    setCursorFreq(freq);
    setCursorPower(mag);
    setCursorTime(null);
  }, []);

  const handleWaterfallCursorMove = useCallback((freq: number | null, time: number | null) => {
    setCursorFreq(freq);
    setCursorTime(time);
    setCursorPower(null);
  }, []);

  // Keyboard shortcuts
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (!analysis) return;
      const detections = analysis.detections;
      if (detections.length === 0) return;

      if (e.key === 'ArrowDown' || e.key === 'ArrowRight') {
        e.preventDefault();
        const currentIdx = detections.findIndex((d) => d.id === selectedDetectionId);
        const nextIdx = Math.min(detections.length - 1, currentIdx + 1);
        setSelectedDetectionId(detections[nextIdx].id);
      } else if (e.key === 'ArrowUp' || e.key === 'ArrowLeft') {
        e.preventDefault();
        const currentIdx = detections.findIndex((d) => d.id === selectedDetectionId);
        const prevIdx = Math.max(0, currentIdx - 1);
        setSelectedDetectionId(detections[prevIdx].id);
      } else if (e.key === ' ') {
        e.preventDefault();
        setBreakdownOpen((prev) => !prev);
      } else if (e.key === 'Escape') {
        setSelectedDetectionId(null);
      }
    };
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [analysis, selectedDetectionId]);

  const selectedDetection: Detection | null =
    analysis?.detections.find((d) => d.id === selectedDetectionId) ?? null;

  const hasAnalysis = !!analysis;

  return (
    <div className="flex flex-col h-screen w-screen bg-rf-window overflow-hidden">
      <Toolbar
        onFileOpen={handleFileOpen}
        onAnalyze={handleAnalyze}
        isAnalyzing={isAnalyzing}
        fileName={file?.name ?? null}
        sampleRate={analysis?.sample_rate ?? null}
        durationSeconds={analysis?.duration_seconds ?? null}
        hasFile={!!file}
        hasAnalysis={hasAnalysis}
      />

      {error && (
        <div className="px-3 py-1.5 bg-rf-alert/20 border-b border-rf-alert text-rf-alert text-[11px] font-mono">
          {error}
        </div>
      )}

      {!hasAnalysis ? (
        <WelcomeScreen onFileOpen={handleFileOpen} onAnalyze={handleAnalyze} />
      ) : (
        <div className="flex flex-1 overflow-hidden">
          {/* Center plots */}
          <div className="flex-1 flex flex-col overflow-hidden bg-rf-recessed">
            {/* FFT Plot */}
            <div className="border-b border-rf-border bg-rf-plot">
              <div className="flex items-center h-6 px-3 bg-rf-panel border-b border-rf-border">
                <span className="text-[10px] text-rf-text-secondary uppercase tracking-wide">FFT / PSD</span>
                {isLoadingSpectrogram && (
                  <span className="ml-3 text-[10px] text-rf-accent">Loading spectrogram...</span>
                )}
              </div>
              <FftPlot
                psdData={psdData}
                noiseFloorDb={analysis?.noise_floor_db ?? null}
                thresholdDb={thresholdDb}
                onThresholdChange={setThresholdDb}
                detections={analysis?.detections ?? []}
                selectedDetectionId={selectedDetectionId}
                onSelectDetection={handleSelectDetection}
                freqMin={freqMin}
                freqMax={freqMax}
                dbMin={dbMin}
                dbMax={dbMax}
                onCursorMove={handleFftCursorMove}
                height={200}
              />
            </div>

            {/* Waterfall + colormap legend */}
            <div className="flex-1 min-h-0 flex bg-rf-plot">
              <div className="flex-1 min-w-0 flex flex-col">
                <div className="flex items-center h-6 px-3 bg-rf-panel border-b border-rf-border">
                  <span className="text-[10px] text-rf-text-secondary uppercase tracking-wide">Waterfall</span>
                </div>
                <div className="flex-1 h-full min-h-0">
                  <Waterfall
                    spectrogram={spectrogram}
                    detections={analysis?.detections ?? []}
                    selectedDetectionId={selectedDetectionId}
                    onSelectDetection={handleSelectDetection}
                    freqMin={freqMin}
                    freqMax={freqMax}
                    onCursorMove={handleWaterfallCursorMove}
                    sampleRate={sampleRate}
                    totalSamples={totalSamples}
                  />
                </div>
              </div>
              <div className="flex flex-col items-center justify-center px-2 bg-rf-panel border-l border-rf-border">
                <ColormapLegend minDb={dbMin} maxDb={dbMax} height={200} />
              </div>
            </div>

            {/* Signal Breakdown (collapsible) */}
            <div
              className={cn(
                'border-t border-rf-border bg-rf-recessed transition-all duration-150 overflow-hidden',
                breakdownOpen ? 'h-72' : 'h-7',
              )}
            >
              <div
                className="flex items-center gap-1.5 h-7 px-3 bg-rf-panel border-b border-rf-border cursor-pointer select-none"
                onClick={() => setBreakdownOpen(!breakdownOpen)}
              >
                {breakdownOpen ? (
                  <ChevronDown className="w-3 h-3 text-rf-text-secondary" />
                ) : (
                  <ChevronUp className="w-3 h-3 text-rf-text-secondary" />
                )}
                <span className="text-[11px] font-medium text-rf-text-primary tracking-wide uppercase">
                  Signal Breakdown
                </span>
                {selectedDetection && (
                  <span className="ml-2 text-[10px] text-rf-text-secondary font-mono">
                    {selectedDetection.id}
                  </span>
                )}
                <span className="ml-auto text-[9px] text-rf-text-secondary/60">
                  Space to toggle
                </span>
              </div>
              {breakdownOpen && (
                <div className="h-[calc(100%-1.75rem)]">
                  <SignalBreakdown
                    layers={layers}
                    isLoading={isLoadingLayers}
                    detection={selectedDetection}
                    sampleRate={sampleRate}
                  />
                </div>
              )}
            </div>
          </div>

          {/* Right sidebar */}
          <div className="w-80 shrink-0 flex flex-col gap-px bg-rf-border overflow-hidden">
            <DockPanel title="Detections" className="flex-1 min-h-0">
              <DetectionsPanel
                detections={analysis?.detections ?? []}
                selectedDetectionId={selectedDetectionId}
                onSelectDetection={handleSelectDetection}
                sampleRate={sampleRate}
              />
            </DockPanel>
            <DockPanel title="Detection Detail" className="shrink-0 max-h-56">
              <DetectionDetailPanel detection={selectedDetection} sampleRate={sampleRate} />
            </DockPanel>
            <DockPanel title="File Info" className="shrink-0 max-h-44">
              <FileInfoPanel fileInfo={fileInfo} />
            </DockPanel>
            <DockPanel title="Pipeline Log" className="shrink-0 max-h-48" defaultOpen={false}>
              <PipelineLogPanel logLines={analysis?.pipeline_log ?? []} />
            </DockPanel>
          </div>
        </div>
      )}

      <StatusBar
        sampleRate={analysis?.sample_rate ?? null}
        durationSeconds={analysis?.duration_seconds ?? null}
        cursorFreq={cursorFreq}
        cursorPower={cursorPower}
        cursorTime={cursorTime}
        detectionCount={analysis?.detections.length ?? 0}
        thresholdDb={thresholdDb}
        noiseFloorDb={analysis?.noise_floor_db ?? null}
        selectedDetectionId={selectedDetectionId}
      />
    </div>
  );
}

export default App;
