import os
import torch
import numpy as np
import torch.nn as nn
import torch.nn.functional as F
import open_clip
import random
from scipy.special import softmax
from mne.time_frequency import psd_array_multitaper
from sklearn.metrics.pairwise import cosine_similarity
from eeg_encoding_utils import generate_and_save_eeg_for_all_images, load_model_endocer, preprocess_image, generate_eeg

def load_vlmodel(model_name='ViT-H-14', model_weights_path=None, precision='fp32', device=None):
    if device is None:
        device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    vlmodel, preprocess_train, feature_extractor = open_clip.create_model_and_transforms(
        model_name=model_name, pretrained=None, precision=precision, device=device
    )
    if model_weights_path:
        model_state_dict = torch.load(model_weights_path, map_location=device)
        vlmodel.load_state_dict(model_state_dict)
    vlmodel.eval()
    return vlmodel, preprocess_train, feature_extractor

def get_image_pool(image_set_path):
    test_images_path = []
    labels = []
    for sub_test_image in sorted(os.listdir(image_set_path)):
        if sub_test_image.startswith('.'):
            continue
        sub_image_path = os.path.join(image_set_path, sub_test_image)
        for image in sorted(os.listdir(sub_image_path)):
            if image.startswith('.'):
                continue
            image_label = os.path.splitext(image)[0]
            labels.append(image_label)
            image_path = os.path.join(sub_image_path, image)
            test_images_path.append(image_path)
    return test_images_path, labels

def calculate_similarity(eeg_path, target_psd, fs, selected_channel_idxes):
    eeg = np.load(eeg_path, allow_pickle=True)
    selected_eeg = eeg[selected_channel_idxes, :]
    psd, _ = psd_array_multitaper(selected_eeg, fs, adaptive=True, normalization='full', verbose=0)
    psd = torch.from_numpy(psd.flatten()).unsqueeze(0)
    return F.cosine_similarity(target_psd, psd).item()

def calculate_loss(eeg_path, target_psd, fs, selected_channel_idxes):
    eeg = np.load(eeg_path, allow_pickle=True)
    selected_eeg = eeg[selected_channel_idxes, :]
    psd, _ = psd_array_multitaper(selected_eeg, fs, adaptive=True, normalization='full', verbose=0)
    psd = torch.from_numpy(psd.flatten()).unsqueeze(0)
    target_psd = torch.tensor(target_psd).view(1, 378)
    loss_fn = nn.MSELoss()
    loss = loss_fn(psd, target_psd)
    return loss

def select(probabilities, similarities, losses, sample_image_paths, sample_eeg_paths):
    chosen_indices = np.random.choice(len(probabilities), size=2, replace=False, p=probabilities)
    chosen_similarities = [similarities[idx] for idx in chosen_indices.tolist()] 
    chosen_losses = [losses[idx] for idx in chosen_indices.tolist()]
    chosen_image_paths = [sample_image_paths[idx] for idx in chosen_indices.tolist()]
    chosen_eeg_paths = [sample_eeg_paths[idx] for idx in chosen_indices.tolist()]
    return chosen_similarities, chosen_losses, chosen_image_paths, chosen_eeg_paths

def load_target_psd(target_path, fs, selected_channel_idxes):
    npy_file = os.path.join(target_path, '00183_tick_183.npy')
    target_signal = np.load(npy_file, allow_pickle=True)
    selected_target_signal = target_signal[selected_channel_idxes, :]
    target_psd, _ = psd_array_multitaper(selected_target_signal, fs, adaptive=True, normalization='full', verbose=0)
    return torch.from_numpy(target_psd.flatten()).unsqueeze(0)

def get_prob_random_sample(test_images_path, model_path, save_path, fs, device, selected_channel_idxes, processed_paths, target_psd):
    available_paths = [path for path in test_images_path if path not in processed_paths]
    sample_image_paths = sorted(random.sample(available_paths, 10))
    processed_paths.update(sample_image_paths)
    sample_image_name = []
    for sample_image_path in sample_image_paths:
        filename = os.path.basename(sample_image_path).split('.')[0]
        sample_image_name.append(filename)
    generate_and_save_eeg_for_all_images(model_path, sample_image_paths, save_path, device, sample_image_name)
    similarities = []
    sample_eeg_paths = []
    losses = []
    for eeg in sorted(os.listdir(save_path)):
        filename = eeg.split('.')[0]
        eeg_path = os.path.join(save_path, eeg)
        sample_eeg_paths.append(eeg_path)
        cs = calculate_similarity(eeg_path, target_psd, fs, selected_channel_idxes)
        similarities.append(cs)
        loss = calculate_loss(eeg_path, target_psd, fs, selected_channel_idxes)
        losses.append(loss)
    probabilities = softmax(similarities)
    chosen_similarities, chosen_losses, chosen_image_paths, chosen_eeg_paths = select(probabilities, similarities, losses, sample_image_paths, sample_eeg_paths)
    return chosen_similarities, chosen_losses, chosen_image_paths, chosen_eeg_paths

def get_target_eeg(model_path, target_image_path, save_dir, device):
    model = load_model_endocer(model_path, device)
    image_tensor = preprocess_image(target_image_path, device)
    synthetic_eeg = generate_eeg(model, image_tensor, device)
    if not os.path.exists(save_dir):
        os.makedirs(save_dir)
    filename = os.path.splitext(os.path.basename(target_image_path))[0]
    target_eeg_path = os.path.join(save_dir, f"{filename}.npy")
    np.save(target_eeg_path, synthetic_eeg)
    return target_eeg_path

def get_selected_channel_idxes(data, fs=250):
    """
    挑选出 PSD 特征之间相似度最小的三个通道。
    
    :param data: EEG 数据，形状为 (n_samples, n_channels, n_timepoints)
    :param fs: 采样频率，默认 250 Hz
    :return: 最显著（相似度最小）的三个通道索引
    """
    n_channels = data.shape[1]
    psds = []

    # 计算每个通道的平均 PSD
    for channel_idx in range(n_channels):
        channel_data = data[:, channel_idx, :]  # (n_samples, n_timepoints)
        psd_sum = 0
        for sample_idx in range(channel_data.shape[0]):
            psd, _ = psd_array_multitaper(channel_data[sample_idx], fs, adaptive=True, normalization='full', verbose=0)
            psd_sum += psd
        psds.append(psd_sum / channel_data.shape[0])  # 计算通道的平均 PSD

    psds = np.array(psds)  # 转为 NumPy 数组，形状为 (n_channels, n_frequencies)

    # 计算通道之间的相似度
    similarity_matrix = cosine_similarity(psds)
    np.fill_diagonal(similarity_matrix, np.nan)  # 将对角线（自相似）设置为 NaN

    # 计算每个通道与其他通道的平均相似度
    mean_similarity = np.nanmean(similarity_matrix, axis=1)

    # 选取平均相似度最小的三个通道
    selected_channel_idxes = np.argsort(mean_similarity)[:3].tolist()
    
    return selected_channel_idxes

def get_target_image(data, selected_channel_idxes, fs=250):
    """
    :param selected_channel_idxes: 使用具有最大视觉特征的通道
    :param data: (n_samples, n_channels, n_timepoints)
    """
    
    selected_data = data[:,selected_channel_idxes, :]

    # PSD 特征提取
    psds = []
    for i in range(selected_data.shape[0]):
        psd, _ = psd_array_multitaper(selected_data[i,:,:], fs, adaptive=True, normalization='full', verbose=0)
        psd = psd.flatten()
        psds.append(psd)
    psds = np.array(psds)
    psds = torch.from_numpy(psds)

    # 取相似度最小的样本，返回其索引
    similarity_matrix = cosine_similarity(psds)
    np.fill_diagonal(similarity_matrix, np.nan)
    mean_similarity = np.nanmean(similarity_matrix, axis=1)
    lowest_index = np.argsort(mean_similarity)[0]
    return lowest_index