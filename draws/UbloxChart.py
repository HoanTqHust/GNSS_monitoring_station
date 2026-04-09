import io
import time
from sklearn.linear_model import LinearRegression
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import base64
import json
import config
class UbloxChart:

    def encode_image(buf):
        with buf:
            return base64.b64encode(buf.getvalue()).decode('utf-8')
    def parseSatelliteInfo(parsed_data):
        satellites = []
        try:
            if parsed_data and parsed_data.identity == "NAV-SAT":
                for i in range(1, parsed_data.numSvs + 1):
                    prn = getattr(parsed_data, f'svId_{i:02}', None)
                    azim = getattr(parsed_data, f'azim_{i:02}', None)
                    elev = getattr(parsed_data, f'elev_{i:02}', None)
                    gnssId = getattr(parsed_data, f'gnssId_{i:02}', None)
                    if prn is not None and azim is not None and elev is not None:
                        satellites.append({'prn': prn, 'azim': azim, 'elev': elev, 'gnssId': gnssId})
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
            if sat['gnssId'] == 0:
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
                    sv_index = sat.svId - 1
                    ps[sv_index] = sat.cpMes + float(navPvt.nano) * 1e-9 * float(sat.doMes)
                except:
                    continue
        return ps, np.zeros(32)

    def process_ubx_data(combined_samples, skyplot_data):
        print(f"[INFO] Plotting with {len(combined_samples)} samples")
        dps = np.zeros((len(combined_samples), 32))
        svId_to_idx = {}
        sv_counter = 0

        for idx in range(len(combined_samples)):
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
                dps[idx, :] -= dps[idx,1]
            dps[idx, :] -= np.round(dps[idx, :])

        satellite_infor = UbloxChart.parseSatelliteInfo(skyplot_data)
        ele_mask_valid = {entry['prn'] for entry in satellite_infor if (entry['elev'] > config.config.ELE_MASK and entry['gnssId'] == 0)}
        valid_columns = np.any(dps != 0, axis=0)
        dps_trimmed = dps[:, valid_columns]
        svIds = [svId for svId, idx in svId_to_idx.items() if valid_columns[idx] and svId in ele_mask_valid]

        fig, ax = plt.subplots(figsize=(12, 6))  # Single subplot now
        for i, svId in enumerate(svIds):
            ax.plot(dps_trimmed[:, i], label=f'SV {svId}', alpha=0.8)

        ax.legend(ncol=4, fontsize=8)
        ax.grid(True)
        ax.set_xlabel('Time Index')
        ax.set_ylabel('Carrier phase differences (Cycle)')
        ax.set_title('Sliding Window Carrier Phase Differences')
        ax.set_ylim([-0.5, 0.5])

        time_idx = np.arange(dps_trimmed.shape[0]).reshape(-1, 1)

        a_list = []
        svId_list = []

        for i, svId in enumerate(svIds):
            y = dps_trimmed[:, i]
            model = LinearRegression()
            model.fit(time_idx, y)
            a = model.coef_[0]
            b = model.intercept_

            a_list.append(a)
            svId_list.append(svId)

            print(f"SV {svId}: a = {a:.6f}, b = {b:.6f}")

        delta_a = 0.0001
        clusters = []

        for i, a in enumerate(a_list):
            found_cluster = False
            for cluster in clusters:
                if abs(a - cluster[0][0]) < delta_a:
                    cluster.append((a, svId_list[i]))
                    found_cluster = True
                    break
            if not found_cluster:
                clusters.append([(a, svId_list[i])])

        spoofing_detected = False
        for cluster in clusters:
            if len(cluster) >= 4:
                spoofing_detected = True
                print("!!! Spoofing detected in cluster:")
                for a_val, sv_id in cluster:
                    print(f"   SV {sv_id} with a = {a_val:.6f}")

        if not spoofing_detected:
            print("No spoofing detected.")

        plt.tight_layout()
        buf = io.BytesIO()
        plt.savefig(buf, format='png', bbox_inches='tight')
        plt.close(fig)
        buf.seek(0)
        return buf, spoofing_detected

    
    @staticmethod
    def raw2ImageSkyplot(raw_data):
        skyplot_data = UbloxChart.parseSatelliteInfo(raw_data)
        buf = UbloxChart.create_skyplot(skyplot_data)
        return UbloxChart.encode_image(buf)
    @staticmethod
    def raw2ImageSpectrum(raw_data):
        spectrum_data = UbloxChart.processDataMonSpan(raw_data)
        buf = UbloxChart.create_spectrum_plot(spectrum_data)
        return UbloxChart.encode_image(buf)
    @staticmethod
    def raw2ImageDps(raw_data, skyplot_data):
        dps_data, spoofing_count = UbloxChart.process_ubx_data(raw_data, skyplot_data)
        if dps_data is None:
            return None
        return UbloxChart.encode_image(dps_data), spoofing_count
