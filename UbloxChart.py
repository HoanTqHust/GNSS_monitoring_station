import io
import time
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import base64
import json
class UbloxChart:
    with open("config.json", "r") as file:
        config = json.load(file)
    fix = config.get("fix", 0)
    BUFFER_SAMPLES = config.get("BUFFER_SAMPLES", 0)
    PLOT_INTERVAL = config.get("PLOT_INTERVAL", 0)
    def encode_image(buf):
        with buf:
            return base64.b64encode(buf.getvalue()).decode('utf-8')
    def processData(parsed_data):
        satellites = []
        try:
            if parsed_data and parsed_data.identity == "NAV-SAT":
                for i in range(1, parsed_data.numSvs + 1):
                    prn = getattr(parsed_data, f'svId_{i:02}', None)
                    azim = getattr(parsed_data, f'azim_{i:02}', None)
                    elev = getattr(parsed_data, f'elev_{i:02}', None)
                    if prn is not None and azim is not None and elev is not None:
                        satellites.append({'prn': prn, 'azim': azim, 'elev': elev})
                time.sleep(1)
        except Exception as e:
            print("Error reading UBX data:", e)
        return satellites
    def create_skyplot(satellites):
        fig = plt.figure(figsize=(6, 6))
        ax = fig.add_subplot(111, polar=True)
        ax.set_theta_zero_location('N')
        ax.set_theta_direction(-1)
        ax.set_ylim(0, 90)
        ax.set_yticks(range(0, 91, 10))
        ax.set_yticklabels([f"{90 - deg}°" for deg in range(0, 91, 10)])
    
        for sat in satellites:
            r = 90 - sat['elev']
            theta = np.deg2rad(sat['azim'])
            ax.plot(theta, r, 'o', label=f"PRN {sat['prn']}")
            ax.text(theta, r, f"{sat['prn']}", fontsize=8, ha='center', va='bottom')
    
        buf = io.BytesIO()
        plt.savefig(buf, format='png')
        plt.close(fig)
        buf.seek(0)
        return buf

    def create_spectrum_plot(mon_span_data):
        spec1 = mon_span_data.get("spectrum_01")
        spec2 = mon_span_data.get("spectrum_02")
    
        fig, axs = plt.subplots(2, 1, figsize=(8, 6))
    
        if spec1 is not None:
            n_bins1 = len(spec1)
            span1 = mon_span_data.get("span_01")
            center1 = mon_span_data.get("center_01")
            freq_start1 = center1 - span1 / 2
            freq_end1 = center1 + span1 / 2
            frequencies1 = np.linspace(freq_start1, freq_end1, n_bins1)
    
            axs[0].plot(frequencies1, spec1, color='blue')
            axs[0].set_title("Spectrum 01")
            axs[0].set_xlabel("Frequency (GHz)")
            axs[0].set_ylabel("Amplitude")
        else:
            axs[0].axis('off')
    
        if spec2 is not None:
            n_bins2 = len(spec2)
            span2 = mon_span_data.get("span_02")
            center2 = mon_span_data.get("center_02")
            freq_start2 = center2 - span2 / 2
            freq_end2 = center2 + span2 / 2
            frequencies2 = np.linspace(freq_start2, freq_end2, n_bins2)
    
            axs[1].plot(frequencies2, spec2, color='green')
            axs[1].set_title("Spectrum 02")
            axs[1].set_xlabel("Frequency (GHz)")
            axs[1].set_ylabel("Amplitude")
        else:
            axs[1].axis('off')
    
        fig.tight_layout()
    
        buf = io.BytesIO()
        plt.savefig(buf, format='png', bbox_inches='tight')
        plt.close(fig)
        buf.seek(0)
        return buf

    def processDataMonSpan(parsed_data):
        mon_span_data = {}
        try:
            if parsed_data and parsed_data.identity == "MON-SPAN":
                for attr in dir(parsed_data):
                    if not attr.startswith('_'):
                        try:
                            value = getattr(parsed_data, attr)
                            if isinstance(value, (int, float, str)):
                                mon_span_data[attr] = value
                            elif isinstance(value, list) and attr.startswith("spectrum_"):
                                mon_span_data[attr] = value
                        except Exception as e:
                            print(f"Error reading attribute {attr}: {e}")
        except Exception as e:
            print("Error processing MON-SPAN data:", e)
        return mon_span_data
    def calc_pseudorange(rxmRaw, navPvt):
        ps = np.zeros(32)
        for sat in rxmRaw.satData:
            if sat.gnssId == 0 and sat.sigId == 0:  # GPS L1 only
                try:
                    # Add your pseudorange calculation here.
                    # For example, assuming a simple difference:
                    ps_val = navPvt.some_measurement - sat.some_measurement
                    # In this example, the calculated value is assigned.
                    ps[sat.svId - 1] = ps_val
                except Exception as e:
                    print(f"Error in calc_pseudorange for svId {sat.svId}: {e}")
                    continue
        # Returning ps and an additional zero array as in the original definition.
        return ps, np.zeros(32)

    def process_ubx_data(combined_samples, BUFFER_SAMPLES):
        if len(combined_samples) < BUFFER_SAMPLES:
            return None

        print(f"[INFO] Plotting with {BUFFER_SAMPLES} samples")
        dps = np.zeros((BUFFER_SAMPLES, 32))
        svId_to_idx = {}
        sv_counter = 0

        for idx in range(BUFFER_SAMPLES):
            rawx1, nav1, rawx2, nav2 = combined_samples[idx]
            ps1, _ = UbloxChart.calc_pseudorange(rawx1, nav1)
            ps2, _ = UbloxChart.calc_pseudorange(rawx2, nav2)
            for i in range(32):
                if ps1[i] != 0 and ps2[i] != 0:
                    svId = i + 1
                    if svId not in svId_to_idx:
                        svId_to_idx[svId] = sv_counter
                        sv_counter += 1
                    dps[idx, svId_to_idx[svId]] = ps1[i] - ps2[i]

            if sv_counter > 0:
                dps[idx, :] -= dps[idx, 0]
            dps[idx, :] -= np.round(dps[idx, :])

        valid_columns = np.any(dps != 0, axis=0)
        dps_trimmed = dps[:, valid_columns]
        svIds = [svId for svId, idx in svId_to_idx.items() if valid_columns[idx]]

        fig, axes = plt.subplots(2, 1, figsize=(12, 8), gridspec_kw={'height_ratios': [3, 1]})
        for i, svId in enumerate(svIds):
            axes[0].plot(dps_trimmed[:, i], label=f'SV {svId}', alpha=0.8)

        axes[0].legend(ncol=4, fontsize=8)
        axes[0].grid(True)
        axes[0].set_xlabel('Time Index')
        axes[0].set_ylabel('Pseudorange Difference (m)')
        axes[0].set_title('Sliding Window Pseudorange Differences')

        sns.heatmap(dps_trimmed.T, cmap="coolwarm", cbar=True, ax=axes[1], linewidths=0.5)
        axes[1].set_yticks(np.arange(len(svIds)) + 0.5)
        axes[1].set_yticklabels([f"SV {svId}" for svId in svIds], rotation=0)
        axes[1].set_xlabel("Time Index")
        axes[1].set_ylabel("Satellite SV ID")
        axes[1].set_title("Heatmap of Pseudorange Differences")

        plt.tight_layout()
        buf = io.BytesIO()
        plt.savefig(buf, format='png', bbox_inches='tight')
        plt.close(fig)
        buf.seek(0)
        return buf
    @staticmethod
    def raw2ImageSkyplot(raw_data):
        skyplot_data = UbloxChart.processData(raw_data)
        buf = UbloxChart.create_skyplot(skyplot_data)
        return UbloxChart.encode_image(buf)
    @staticmethod
    def raw2ImageSpectrum(raw_data):
        spectrum_data = UbloxChart.processDataMonSpan(raw_data)
        buf = UbloxChart.create_spectrum_plot(spectrum_data)
        return UbloxChart.encode_image(buf)
    @staticmethod
    def raw2ImageDps(raw_data):
        dps_data = UbloxChart.process_ubx_data(raw_data, UbloxChart.BUFFER_SAMPLES)
        if dps_data is None:
            return None
        return UbloxChart.encode_image(dps_data)
