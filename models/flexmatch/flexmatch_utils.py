import torch
import math
import torch.nn.functional as F
import numpy as np
from collections import Counter

from train_utils import ce_loss


class Get_Scalar:
  def __init__(self, value):
    self.value = value

  def get_value(self, iter):
    return self.value

  def __call__(self, iter):
    return self.value


def consistency_loss(logits_s, logits_w, class_acc, args, p_target, p_model, name='ce',
                     T=1.0, p_cutoff=0.0, use_hard_labels=True, use_DA=False):
  assert name in ['ce', 'L2']
  logits_w = logits_w.detach()
  label_counter_dict = dict(Counter(torch.max(logits_w, dim=-1)[1].cpu().detach().numpy()))
  for j in range(args.num_classes):
    if j not in list(label_counter_dict.keys()):
      label_counter_dict[j] = 1
  logits_order = np.argsort(list(label_counter_dict.keys()))
  logits_inflation_factor = np.array(list(label_counter_dict.values())).astype('uint8')[logits_order] ** .5
  logits_inflation_factor /= np.max(logits_inflation_factor)
  logits_inflation_factor = torch.from_numpy(logits_inflation_factor).view(1, -1).cuda(args.gpu)

  logits_s, logits_w = logits_s / logits_inflation_factor, logits_w / logits_inflation_factor

  if name == 'L2':
    assert logits_w.size() == logits_s.size()
    return F.mse_loss(logits_s, logits_w, reduction='mean')

  elif name == 'L2_mask':
    pass

  elif name == 'ce':
    pseudo_label = torch.softmax(logits_w, dim=-1)
    if use_DA:
      if p_model == None:
        p_model = torch.mean(pseudo_label.detach(), dim=0)
      else:
        p_model = p_model * 0.999 + torch.mean(pseudo_label.detach(), dim=0) * 0.001
      pseudo_label = pseudo_label * p_target / p_model
      pseudo_label = (pseudo_label / pseudo_label.sum(dim=-1, keepdim=True))

    max_probs, max_idx = torch.max(pseudo_label, dim=-1)
    # mask = max_probs.ge(p_cutoff * (class_acc[max_idx] + 1.) / 2).float()  # linear
    # mask = max_probs.ge(p_cutoff * (1 / (2. - class_acc[max_idx]))).float()  # low_limit
    mask = max_probs.ge(p_cutoff * (class_acc[max_idx] /
                                           (2. - class_acc[max_idx]))).float()  # convex
    # mask = max_probs.ge(p_cutoff * (torch.log(class_acc[max_idx] + 1.) + 0.5)/(math.log(2) + 0.5)).float()  # concave
    select = max_probs.ge(p_cutoff).long()
    if use_hard_labels:
      masked_loss = ce_loss(logits_s, max_idx, use_hard_labels, reduction='none') * mask
    else:
      pseudo_label = torch.softmax(logits_w / T, dim=-1)
      masked_loss = ce_loss(logits_s, pseudo_label, use_hard_labels) * mask
    return masked_loss.mean(), mask.mean(), select, max_idx.long(), p_model

  else:
    assert Exception('Not Implemented consistency_loss')
